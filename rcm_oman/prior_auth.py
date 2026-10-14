"""Prior authorisation: created automatically for Manual-approval coverages, sent through the
transport or handled manually, and its decision applied back onto Marley's coverages."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, now_datetime, today

from rcm_oman.utils import ensure_denial_code, int_setting, setting

DECIDED = ("Approved", "Partially Approved", "Rejected")


def ensure_prior_authorization(doc, method=None):
	"""Patient Insurance Coverage on_update: a Manual-approval coverage needs an authorisation."""
	if doc.docstatus != 0 or doc.status != "Draft" or doc.mode_of_approval != "Manual":
		return
	if doc.get("prior_authorization") or doc.flags.get("rcm_skip_auth"):
		return
	if not int(setting("auto_create_prior_auth", 1) or 0):
		return

	par = make_prior_authorization([doc.name])
	doc.db_set("prior_authorization", par.name, update_modified=False)

	if par.channel == "Dhamani" and int(setting("auto_send_prior_auth", 1) or 0):
		par.submit()


def make_prior_authorization(coverage_names, practitioner=None, diagnosis_code=None, clinical_notes=None):
	coverages = [frappe.get_doc("Patient Insurance Coverage", n) for n in coverage_names]
	first = coverages[0]
	for c in coverages[1:]:
		if c.insurance_policy != first.insurance_policy:
			frappe.throw(_("All coverages on one authorisation must share the same policy"))

	from rcm_oman.claims.encounter import encounter_for_coverage

	encounter = encounter_for_coverage(first)
	par = frappe.new_doc("Prior Authorization Request")
	par.update(
		{
			"patient": first.patient,
			"insurance_policy": first.insurance_policy,
			"company": first.company,
			"branch": first.get("branch"),
			"posting_date": today(),
			"encounter_type": first.get("encounter_type") or "Outpatient",
			"practitioner": practitioner or (encounter.practitioner if encounter else None),
			"clinical_notes": clinical_notes,
			"diagnosis_code": diagnosis_code,
		}
	)
	if encounter is not None:
		par.source_doctype, par.source_name = "Patient Encounter", encounter.name
		if not par.diagnosis_code:
			from rcm_oman.claims.encounter import diagnosis_code_values

			names = diagnosis_code_values(encounter)
			if names:
				par.diagnosis_code = names[0]
	for c in coverages:
		par.append(
			"items",
			{
				"insurance_coverage": c.name,
				"item_code": c.item_code,
				"template_dt": c.template_dt,
				"template_dn": c.template_dn,
				"code_system": c.code_system,
				"code_value": c.code_value,
				"qty": c.qty or 1,
				"requested_amount": flt(c.coverage_amount) or flt(c.amount),
			},
		)
	par.insert(ignore_permissions=True)
	for c in coverages:
		if not c.get("prior_authorization"):
			frappe.db.set_value("Patient Insurance Coverage", c.name, "prior_authorization", par.name)
	return par


def apply_decision(par_name, decision):
	"""Apply a canonical AuthDecision dict (from the payer or recorded manually) to the request and coverages."""
	par = frappe.get_doc("Prior Authorization Request", par_name)
	status = decision.get("status")

	if status in ("Pending", None):
		par.db_set("payer_reference", decision.get("payer_reference") or par.payer_reference)
		return par

	if status == "Information Requested":
		par.db_set(
			{
				"status": "Information Requested",
				"decision_reason": decision.get("message"),
				"payer_reference": decision.get("payer_reference") or par.payer_reference,
			}
		)
		_notify(par, _("Payer requested more information on {0}").format(par.name))
		return par

	lines = {str(line.get("line_id")): line for line in decision.get("lines") or []}
	total_approved = 0.0
	for item in par.items:
		line = lines.get(item.name) or lines.get(item.insurance_coverage)
		if line is None:
			# whole-request decision without per-line detail
			line = {
				"status": status,
				"approved_amount": item.requested_amount if status == "Approved" else 0,
				"approved_qty": item.qty if status == "Approved" else 0,
			}
		item.status = line.get("status") or status
		if item.status == "Rejected":
			item.approved_amount, item.approved_qty = 0, 0
		else:
			item.approved_amount = flt(
				line.get("approved_amount")
				if line.get("approved_amount") is not None
				else item.requested_amount
			)
			item.approved_qty = flt(
				line.get("approved_qty") if line.get("approved_qty") is not None else item.qty
			)
		item.reason_code = ensure_denial_code(line.get("denial_code"), line.get("denial_reason"))
		item.reason = line.get("denial_reason")
		total_approved += flt(item.approved_amount)

	par.status = status
	par.approved_amount = total_approved
	par.payer_reference = decision.get("payer_reference") or par.payer_reference
	par.approval_number = decision.get("approval_number") or par.approval_number
	par.decision_reason = decision.get("message") or par.decision_reason
	par.decided_on = now_datetime()
	par.valid_till = (
		decision.get("valid_till")
		or par.valid_till
		or add_days(today(), int_setting("default_auth_validity_days", 30))
	)
	par.flags.ignore_validate_update_after_submit = True
	par.save(ignore_permissions=True)

	for item in par.items:
		if item.insurance_coverage:
			_apply_to_coverage(item, par)

	_notify(par, _("Prior authorisation {0}: {1}").format(par.name, par.status))
	return par


def _apply_to_coverage(item, par):
	coverage = frappe.get_doc("Patient Insurance Coverage", item.insurance_coverage)
	if coverage.docstatus != 0:
		return
	coverage.flags.silent = True
	coverage.flags.rcm_skip_auth = True
	coverage.prior_authorization = par.name
	if item.status == "Rejected":
		coverage.status = "Rejected"
		coverage.authorized_amount = 0
	else:
		coverage.status = "Approved"
		coverage.authorized_amount = flt(item.approved_amount)
		if item.approved_qty and flt(item.approved_qty) < flt(coverage.qty):
			coverage.qty = item.approved_qty
	coverage.save(ignore_permissions=True)
	coverage.submit()


@frappe.whitelist()
def record_manual_decision(name, status, approval_number=None, valid_till=None, reason=None, items=None):
	"""Manual channel: staff record what the payer decided (portal / email / fax)."""
	frappe.has_permission("Prior Authorization Request", "submit", name, throw=True)
	par = frappe.get_doc("Prior Authorization Request", name)
	if par.docstatus != 1:
		frappe.throw(_("Submit the request first, then record the payer decision"))
	if status in ("Approved", "Partially Approved") and not approval_number:
		frappe.throw(_("Approval number is required"))
	items = frappe.parse_json(items) if isinstance(items, str) else (items or [])
	decision = {
		"status": status,
		"approval_number": approval_number,
		"valid_till": valid_till,
		"message": reason,
		"lines": [
			{
				"line_id": row.get("name"),
				"status": row.get("status") or status,
				"approved_amount": row.get("approved_amount"),
				"approved_qty": row.get("approved_qty"),
				"denial_code": row.get("reason_code"),
				"denial_reason": row.get("reason"),
			}
			for row in items
		],
	}
	return apply_decision(name, decision).as_dict()


def on_send_failure(par_name, error, permanent):
	par = frappe.get_doc("Prior Authorization Request", par_name)
	if permanent:
		par.db_set({"status": "Error", "decision_reason": str(error)[:500]})
		_notify(par, _("Prior authorisation {0} was rejected by the platform: {1}").format(par.name, error))


def expire_authorizations():
	for name in frappe.get_all(
		"Prior Authorization Request",
		filters={
			"docstatus": 1,
			"status": ("in", ["Approved", "Partially Approved"]),
			"valid_till": ("<", today()),
		},
		pluck="name",
	):
		frappe.db.set_value("Prior Authorization Request", name, "status", "Expired")


def is_authorization_valid(par_name, service_date=None):
	if not par_name:
		return False
	status, valid_till = frappe.db.get_value(
		"Prior Authorization Request", par_name, ["status", "valid_till"]
	)
	if status not in ("Approved", "Partially Approved"):
		return False
	if valid_till and getdate(valid_till) < getdate(service_date or today()):
		return False
	return True


def _notify(par, message):
	try:
		owner = par.owner if par.owner not in ("Administrator", "Guest") else None
		if owner:
			frappe.publish_realtime("msgprint", {"message": message, "indicator": "blue"}, user=owner)
		par.add_comment("Info", message)
	except Exception:
		pass
