"""Parse a payer remittance statement (CSV or XLSX) into Remittance Line rows.

Accepted headers (case-insensitive, spaces or underscores):
  external_claim_id | claim_id
  insurance_claim, claim_coverage | line_id        (optional when external id is given)
  paid_amount | paid
  denied_amount | denied | rejected_amount
  denial_code | reason_code
  denial_reason | remarks
  claimed_amount | claimed                         (optional)
"""

import frappe
from frappe import _
from frappe.utils import flt

ALIASES = {
	"external_claim_id": ("external_claim_id", "claim_id", "payer_claim_id"),
	"insurance_claim": ("insurance_claim",),
	"claim_coverage": ("claim_coverage", "line_id"),
	"paid_amount": ("paid_amount", "paid"),
	"denied_amount": ("denied_amount", "denied", "rejected_amount"),
	"denial_code": ("denial_code", "reason_code"),
	"denial_reason": ("denial_reason", "remarks", "reason"),
	"claimed_amount": ("claimed_amount", "claimed", "claim_amount"),
}


def normalize_header(h):
	return str(h or "").strip().lower().replace(" ", "_").replace("-", "_")


def rows_from_table(table):
	"""table: list of lists, first row = header. Returns list of dicts for Remittance Line."""
	if not table:
		return []
	header = [normalize_header(h) for h in table[0]]
	index = {}
	for target, names in ALIASES.items():
		for n in names:
			if n in header:
				index[target] = header.index(n)
				break
	if "paid_amount" not in index or not ({"external_claim_id", "claim_coverage"} & set(index)):
		raise ValueError("Remittance file needs paid_amount and external_claim_id or claim_coverage columns")

	out = []
	for raw in table[1:]:
		if not raw or not any(str(c or "").strip() for c in raw):
			continue

		def cell(key):
			i = index.get(key)
			return raw[i] if i is not None and i < len(raw) else None

		row = {
			"external_claim_id": str(cell("external_claim_id") or "").strip() or None,
			"insurance_claim": str(cell("insurance_claim") or "").strip() or None,
			"claim_coverage": str(cell("claim_coverage") or "").strip() or None,
			"paid_amount": flt(cell("paid_amount")),
			"denied_amount": flt(cell("denied_amount")),
			"denial_code": str(cell("denial_code") or "").strip() or None,
			"denial_reason": str(cell("denial_reason") or "").strip() or None,
			"claimed_amount": flt(cell("claimed_amount")),
		}
		out.append(row)
	return out


def read_remittance_file(file_url):
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	content = file_doc.get_content()
	name = (file_doc.file_name or "").lower()
	if name.endswith(".xlsx"):
		from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file

		table = read_xlsx_file_from_attached_file(fcontent=content)
	elif name.endswith(".csv"):
		from frappe.utils.csvutils import read_csv_content

		table = read_csv_content(content)
	else:
		frappe.throw(_("Remittance file must be .csv or .xlsx"))
	try:
		rows = rows_from_table(table)
	except ValueError as e:
		frappe.throw(str(e))
	from rcm_oman.utils import ensure_denial_code

	for r in rows:
		r["denial_code"] = ensure_denial_code(r["denial_code"], r["denial_reason"], source="Payer")
	return rows
