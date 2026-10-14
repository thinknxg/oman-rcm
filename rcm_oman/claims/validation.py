"""Pre-submission claim validation (both channels): catch what the payer would reject."""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from his_oman.licensing import check_practitioner_licence
from rcm_oman.claims.encounter import diagnosis_codes, encounter_for_claim_row
from rcm_oman.prior_auth import is_authorization_valid
from rcm_oman.utils import setting

ERROR, WARNING = "error", "warning"


def service_date(row):
	return row.get("insurance_coverage_posting_date") or row.get("sales_invoice_posting_date")


def enrich_row(row):
	"""Fill practitioner, diagnosis codes and authorisation on a claim row from the clinical record."""
	encounter = encounter_for_claim_row(row)
	if encounter is not None:
		row.practitioner = row.get("practitioner") or encounter.practitioner
		codes = diagnosis_codes(encounter)
		if codes:
			row.diagnosis_codes = ", ".join(codes[:12])
	if row.insurance_coverage and not row.get("prior_authorization"):
		row.prior_authorization = frappe.db.get_value(
			"Patient Insurance Coverage", row.insurance_coverage, "prior_authorization"
		)
	return encounter


def validate_claim(claim, channel):
	issues = []

	def add(level, message, row=None):
		issues.append({"level": level, "row": row.idx if row else None, "message": message})

	if not claim.get("facility_licence"):
		add(ERROR, _("No active Facility Licence for branch {0}").format(claim.get("branch") or "-"))

	if channel == "Dhamani" and not frappe.db.get_value(
		"Insurance Payor", claim.insurance_payor, "dhamani_payer_code"
	):
		add(ERROR, _("Insurance Payor {0} has no Dhamani Payer Code").format(claim.insurance_payor))

	require_dx = cint(setting("require_diagnosis_code", 1))
	require_lic = cint(setting("require_practitioner_licence", 1))
	id_checked = set()

	for row in claim.coverages:
		if row.status == "Cancelled":
			continue
		enrich_row(row)
		date = service_date(row)

		if flt(row.claim_amount) <= 0:
			add(ERROR, _("Claim amount must be more than zero"), row)

		if not row.code_value:
			add(ERROR if channel == "Dhamani" else WARNING, _("Service has no medical code"), row)

		if require_dx and not row.get("diagnosis_codes"):
			add(ERROR, _("No coded diagnosis on the encounter"), row)

		if require_lic:
			ok, message = check_practitioner_licence(row.get("practitioner"), date)
			if not ok:
				add(ERROR, message, row)

		if row.mode_of_approval == "Manual" and not is_authorization_valid(
			row.get("prior_authorization"), date
		):
			add(ERROR, _("Prior authorisation missing, not approved or expired"), row)

		if row.policy_expiry_date and date and getdate(row.policy_expiry_date) < getdate(date):
			add(ERROR, _("Policy expired before the service date"), row)

		if channel == "Dhamani" and row.patient not in id_checked:
			id_checked.add(row.patient)
			if not frappe.db.get_value("Patient", row.patient, "civil_id"):
				add(ERROR, _("Patient {0} has no ID number").format(row.patient), row)

	return issues


def format_report(issues):
	if not issues:
		return _("Passed: no issues found")
	lines = []
	for i in issues:
		prefix = _("Row {0}").format(i["row"]) if i["row"] else _("Claim")
		lines.append(f"[{i['level'].upper()}] {prefix}: {i['message']}")
	return "\n".join(lines)


def has_errors(issues):
	return any(i["level"] == ERROR for i in issues)
