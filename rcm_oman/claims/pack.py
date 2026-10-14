"""Manual channel: claim pack (Excel) for payers not on Dhamani or while the link is down."""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from frappe.utils.file_manager import save_file
from frappe.utils.xlsxutils import make_xlsx

from rcm_oman.claims.builder import build_submission

HEADER = [
	"Claim Key",
	"Line ID",
	"Patient",
	"Patient Name",
	"ID Type",
	"ID Number",
	"Policy Number",
	"Member ID",
	"Encounter Type",
	"Service Date",
	"Service Code",
	"Description",
	"Qty",
	"Gross (OMR)",
	"Patient Share (OMR)",
	"Claimed (OMR)",
	"Authorisation No",
	"Diagnosis Codes",
	"Practitioner Licence",
	"Facility Licence",
	"Resubmission Of",
]


def build_rows(claim):
	submission = build_submission(claim)
	rows = [HEADER]
	for c in submission.claims:
		for line in c.lines:
			rows.append(
				[
					c.claim_key,
					line.line_id,
					c.member.patient_id,
					c.member.name,
					c.member.id_type,
					c.member.id_number,
					c.member.policy_number,
					c.member.member_id,
					c.encounter_type,
					line.service_date,
					line.code,
					line.description,
					line.qty,
					flt(line.gross, 3),
					flt(line.patient_share, 3),
					flt(line.net, 3),
					line.authorization,
					", ".join(c.diagnosis_codes),
					line.practitioner_licence or c.practitioner_licence,
					c.party.facility_licence,
					c.resubmission_of,
				]
			)
	totals = sum(flt(r[15]) for r in rows[1:])
	rows.append([""] * 14 + [_("Total"), flt(totals, 3)] + [""] * 5)
	return rows


@frappe.whitelist()
def generate_manual_pack(claim_name):
	claim = frappe.get_doc("Insurance Claim", claim_name)
	claim.check_permission("read")
	xlsx = make_xlsx(build_rows(claim), "Claim")
	fname = f"{claim.name}-claim-pack.xlsx"
	f = save_file(fname, xlsx.getvalue(), "Insurance Claim", claim.name, is_private=1)
	if claim.docstatus == 1 and claim.get("submission_status") in (None, "", "Not Sent", "Queued"):
		claim.db_set({"submission_status": "Manual Pack Generated", "submitted_on": now_datetime()})
	return f.file_url
