"""Inbound events from a transport (dhamani_gateway). All payloads are canonical dicts."""

import frappe
from frappe.utils import flt, now_datetime, today


def on_acknowledgement(reference_doctype, reference_name, external_reference=None):
	if reference_doctype == "Insurance Claim":
		values = {"submission_status": "Sent", "submitted_on": now_datetime()}
		if external_reference:
			values["payer_batch_reference"] = external_reference
		frappe.db.set_value("Insurance Claim", reference_name, values)
	elif reference_doctype == "Prior Authorization Request" and external_reference:
		frappe.db.set_value(
			"Prior Authorization Request", reference_name, "payer_reference", external_reference
		)


def on_eligibility_response(reference_name, response):
	from rcm_oman.eligibility import apply_eligibility_response

	return apply_eligibility_response(reference_name, response)


def on_auth_decision(reference_name, response):
	from rcm_oman.prior_auth import apply_decision

	return apply_decision(reference_name, response)


def on_claim_response(reference_name, response):
	from rcm_oman.claims.response import apply_claim_response

	return apply_claim_response(reference_name, response)


def on_send_failure(reference_doctype, reference_name, message_type, error, permanent):
	if reference_doctype == "Insurance Claim":
		from rcm_oman.claims.response import on_send_failure as claim_failure

		claim_failure(reference_name, error, permanent)
	elif reference_doctype == "Prior Authorization Request":
		from rcm_oman.prior_auth import on_send_failure as auth_failure

		auth_failure(reference_name, error, permanent)
	elif reference_doctype == "Eligibility Check":
		frappe.db.set_value(
			"Eligibility Check", reference_name, {"status": "Error", "response_message": str(error)[:500]}
		)


def on_remittance(response, auto_submit=True):
	"""Canonical Remittance -> Remittance Advice (source Dhamani). Submitted automatically when every
	line matches a claim and a bank account is known; otherwise left in Draft for finance."""
	payment_reference = response.get("payment_reference")
	if payment_reference and frappe.db.exists(
		"Remittance Advice", {"payment_reference": payment_reference, "docstatus": ("<", 2)}
	):
		return None

	payor = None
	if response.get("payer_code"):
		payor = frappe.db.get_value("Insurance Payor", {"dhamani_payer_code": response["payer_code"]}, "name")
	company = None
	if response.get("provider_code"):
		company = frappe.db.get_value(
			"Facility Licence", {"dhamani_provider_code": response["provider_code"]}, "company"
		)

	ra = frappe.new_doc("Remittance Advice")
	ra.source = "Dhamani"
	ra.payment_reference = payment_reference
	ra.payment_date = response.get("payment_date") or today()
	ra.insurance_payor = payor
	ra.company = company
	for line in response.get("lines") or []:
		ra.append(
			"items",
			{
				"external_claim_id": line.get("external_claim_id"),
				"claim_coverage": line.get("line_id"),
				"claimed_amount": flt(line.get("claimed_amount")),
				"paid_amount": flt(line.get("paid_amount")),
				"denied_amount": flt(line.get("denied_amount")),
				"denial_code": _denial(line),
				"denial_reason": line.get("denial_reason"),
			},
		)
	if not ra.insurance_payor or not ra.company:
		ra.flags.ignore_mandatory = True
	ra.insert(ignore_permissions=True)
	if (
		auto_submit
		and ra.insurance_payor
		and ra.company
		and not ra.unmatched_lines_count()
		and ra.resolve_paid_to()
	):
		try:
			ra.flags.ignore_permissions = True
			ra.submit()
		except Exception:
			frappe.log_error(title=f"RCM: auto-submit of {ra.name} failed")
	return ra.name


def _denial(line):
	from rcm_oman.utils import ensure_denial_code

	return ensure_denial_code(line.get("denial_code"), line.get("denial_reason"))
