"""Apply payer / platform claim responses to Marley's Insurance Claim."""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from rcm_oman.denials import open_case
from rcm_oman.utils import ensure_denial_code

SUBMISSION_STATUS = {
	"Accepted": "Accepted",
	"Rejected": "Rejected by Platform",
	"Information Requested": "Information Requested",
	"Adjudicated": "Adjudicated",
}


def _rows_for_key(claim, claim_key):
	invoice = (claim_key or "").split("/", 1)[-1]
	return [r for r in claim.coverages if (r.sales_invoice or r.insurance_coverage) == invoice]


def apply_line(claim, row, decision):
	status = decision.get("status")
	reason = decision.get("denial_reason")
	code = ensure_denial_code(decision.get("denial_code"), reason)
	claimed = flt(row.claim_amount)

	if status in ("Approved", "Partially Approved"):
		approved = decision.get("approved_amount")
		approved = claimed if approved is None else min(flt(approved), claimed)
		row.status = "Approved"
		row.payer_adjudicated = 1
		row.payer_approved_amount = approved
		row.denial_code = code if approved < claimed else None
		row.payment_error_reason = reason if approved < claimed else ""
		if approved < claimed:
			open_case(claim, row, claimed - approved, code, reason)
	elif status == "Rejected":
		row.status = "Rejected"
		row.payer_adjudicated = 1
		row.payer_approved_amount = 0
		row.denial_code = code
		row.payment_error_reason = reason or code or _("Rejected by payer")
		open_case(claim, row, claimed, code, reason)


def apply_claim_response(claim_name, response):
	claim = frappe.get_doc("Insurance Claim", claim_name)
	overall = response.get("status")
	if response.get("batch_reference"):
		claim.payer_batch_reference = response["batch_reference"]
	if response.get("message"):
		claim.payer_message = response["message"]
	if not claim.get("submitted_on"):
		claim.submitted_on = now_datetime()

	by_id = {r.name: r for r in claim.coverages}
	adjudicated_any = False
	for result in response.get("claims") or []:
		group = _rows_for_key(claim, result.get("claim_key"))
		for row in group:
			if result.get("external_claim_id"):
				row.external_claim_id = result["external_claim_id"]
		for decision in result.get("lines") or []:
			row = by_id.get(str(decision.get("line_id")))
			if row is None:
				continue
			apply_line(claim, row, decision)
			adjudicated_any = True
		if result.get("status") == "Information Requested" and result.get("message"):
			claim.payer_message = result["message"]
			overall = "Information Requested"

	if adjudicated_any and overall in (None, "Accepted"):
		overall = "Adjudicated"
	if overall in SUBMISSION_STATUS:
		claim.submission_status = SUBMISSION_STATUS[overall]

	claim.flags.ignore_validate_update_after_submit = True
	claim.save(ignore_permissions=True)

	if claim.submission_status in ("Rejected by Platform", "Information Requested"):
		_notify(claim, _("{0}: {1}").format(claim.submission_status, claim.payer_message or ""))
	return claim


def on_send_failure(claim_name, error, permanent):
	claim = frappe.get_doc("Insurance Claim", claim_name)
	if permanent:
		claim.db_set({"submission_status": "Rejected by Platform", "payer_message": str(error)[:1000]})
		_notify(claim, _("Claim {0} was rejected by the platform: {1}").format(claim.name, error))


def _notify(claim, message):
	claim.add_comment("Info", message)
	recipients = [claim.owner] if claim.owner not in ("Administrator", "Guest") else []
	for user in recipients:
		frappe.publish_realtime("msgprint", {"message": message, "indicator": "orange"}, user=user)
