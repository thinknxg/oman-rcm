# Copyright (c) 2026, Kreatao and contributors
# For license information, please see license.txt

"""Remittance Advice: what the payer paid and denied, line by line.

On submit, per Insurance Claim:
1. lines are applied to the claim rows (payer approved amount, denials -> Denial Cases);
2. one Payment Entry is posted against the coverage Journal Entries Marley created at invoicing,
   allocating exactly what was paid per line. Marley's Payment Entry hook then updates the
   claim's paid amounts, and the RCM claim override closes fully paid lines.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from rcm_oman.denials import mark_recovered, open_case
from rcm_oman.utils import ensure_denial_code

TOLERANCE = 0.0005


class RemittanceAdvice(Document):
	def validate(self):
		self.match_lines()
		self.total_paid = sum(flt(i.paid_amount) for i in self.items)
		self.total_denied = sum(flt(i.denied_amount) for i in self.items)
		if self.docstatus == 0:
			self.status = "Draft"

	def match_lines(self):
		for line in self.items:
			row = None
			if line.claim_coverage:
				row = frappe.db.get_value(
					"Insurance Claim Coverage",
					line.claim_coverage,
					["name", "parent", "insurance_coverage", "patient", "claim_amount", "external_claim_id"],
					as_dict=True,
				)
			if row is None and line.external_claim_id:
				candidates = frappe.get_all(
					"Insurance Claim Coverage",
					filters={
						"external_claim_id": line.external_claim_id,
						"parenttype": "Insurance Claim",
						"docstatus": 1,
					},
					fields=[
						"name",
						"parent",
						"insurance_coverage",
						"patient",
						"claim_amount",
						"external_claim_id",
					],
				)
				if len(candidates) == 1:
					row = candidates[0]
			if row is None and line.insurance_claim and line.insurance_coverage:
				row = frappe.db.get_value(
					"Insurance Claim Coverage",
					{"parent": line.insurance_claim, "insurance_coverage": line.insurance_coverage},
					["name", "parent", "insurance_coverage", "patient", "claim_amount", "external_claim_id"],
					as_dict=True,
				)
			if row:
				line.claim_coverage = row.name
				line.insurance_claim = row.parent
				line.insurance_coverage = row.insurance_coverage
				line.patient = row.patient
				line.external_claim_id = line.external_claim_id or row.external_claim_id
				line.claimed_amount = flt(line.claimed_amount) or flt(row.claim_amount)
				if line.match_status != "Applied":
					line.match_status = "Matched"
				payor = frappe.db.get_value("Insurance Claim", row.parent, "insurance_payor")
				if self.insurance_payor and payor != self.insurance_payor:
					frappe.throw(
						_("Row {0}: claim {1} belongs to payer {2}").format(line.idx, row.parent, payor)
					)
			else:
				line.match_status = "Unmatched"

	def unmatched_lines_count(self):
		return sum(1 for i in self.items if i.match_status == "Unmatched")

	def resolve_paid_to(self):
		if self.paid_to:
			return self.paid_to
		if self.mode_of_payment and self.company:
			from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

			self.paid_to = (get_bank_cash_account(self.mode_of_payment, self.company) or {}).get("account")
		if not self.paid_to and self.company:
			self.paid_to = frappe.get_cached_value(
				"Company", self.company, "default_bank_account"
			) or frappe.get_cached_value("Company", self.company, "default_cash_account")
		if self.paid_to and not self.is_new():
			self.db_set("paid_to", self.paid_to)
		return self.paid_to

	def before_submit(self):
		if not self.items:
			frappe.throw(_("Add remittance lines"))
		if not self.resolve_paid_to():
			frappe.throw(_("Set the Bank / Cash Account the payer paid into"))
		for line in self.items:
			if flt(line.paid_amount) < 0 or flt(line.denied_amount) < 0:
				frappe.throw(_("Row {0}: amounts cannot be negative").format(line.idx))
			if (
				line.match_status == "Matched"
				and flt(line.paid_amount) + flt(line.denied_amount) > flt(line.claimed_amount) + TOLERANCE
			):
				frappe.throw(_("Row {0}: paid + denied exceeds the claimed amount").format(line.idx))

	def on_submit(self):
		payment_entries = []
		by_claim = {}
		for line in self.items:
			if line.match_status == "Matched":
				by_claim.setdefault(line.insurance_claim, []).append(line)

		for claim_name, lines in by_claim.items():
			claim = self.apply_to_claim(claim_name, lines)
			pe = self.make_payment_entry(claim, lines)
			if pe:
				payment_entries.append(pe)
				if claim.get("resubmission_of"):
					for line in lines:
						if flt(line.paid_amount) > 0:
							mark_recovered(line.insurance_coverage, line.paid_amount, claim.name)
			for line in lines:
				line.db_set("match_status", "Applied")

		unmatched = self.unmatched_lines_count()
		self.db_set(
			{
				"payment_entries": "\n".join(payment_entries),
				"unmatched_lines": unmatched,
				"status": "Partly Applied" if unmatched else "Applied",
			}
		)

	def apply_to_claim(self, claim_name, lines):
		claim = frappe.get_doc("Insurance Claim", claim_name)
		rows = {r.name: r for r in claim.coverages}
		for line in lines:
			row = rows.get(line.claim_coverage)
			if row is None:
				continue
			claimed = flt(row.claim_amount)
			paid = flt(line.paid_amount)
			denied = flt(line.denied_amount)
			code = ensure_denial_code(line.denial_code, line.denial_reason)
			if paid <= TOLERANCE and denied >= claimed - TOLERANCE:
				row.status = "Rejected"
				row.payer_adjudicated = 1
				row.payer_approved_amount = 0
				row.denial_code = code
				row.payment_error_reason = (
					line.denial_reason or code or _("Denied in remittance {0}").format(self.name)
				)
				open_case(claim, row, claimed, code, line.denial_reason)
				continue
			# payer approved = everything not denied (paid now, or still to be paid)
			if denied > TOLERANCE:
				approved = claimed - denied
			elif row.get("payer_adjudicated"):
				approved = flt(row.payer_approved_amount)
			else:
				approved = claimed
			approved = min(max(approved, paid), claimed)
			row.status = "Approved"
			row.payer_adjudicated = 1
			row.payer_approved_amount = approved
			if denied > TOLERANCE:
				row.denial_code = code
				row.payment_error_reason = line.denial_reason or code or ""
				open_case(claim, row, denied, code, line.denial_reason)
		claim.flags.ignore_validate_update_after_submit = True
		claim.save(ignore_permissions=True)
		return claim

	def make_payment_entry(self, claim, lines):
		refs = []
		rows = {r.name: r for r in claim.coverages}
		for line in lines:
			row = rows.get(line.claim_coverage)
			if row is None or flt(line.paid_amount) <= TOLERANCE or not row.journal_entry:
				continue
			refs.append((row, flt(line.paid_amount, 3)))
		if not refs:
			return None

		total = flt(sum(a for _r, a in refs), 3)
		pe = frappe.new_doc("Payment Entry")
		pe.payment_type = "Receive"
		pe.company = claim.company
		pe.posting_date = self.payment_date
		pe.mode_of_payment = self.mode_of_payment
		pe.party_type = "Customer"
		pe.party = claim.customer
		pe.paid_to = self.paid_to
		pe.paid_amount = total
		pe.received_amount = total
		pe.reference_no = self.payment_reference
		pe.reference_date = self.payment_date
		pe.remarks = _("Remittance {0} ({1}) for Insurance Claim {2}").format(
			self.name, self.payment_reference, claim.name
		)
		if pe.meta.has_field("branch") and claim.get("branch"):
			pe.branch = claim.branch
		for row, amount in refs:
			outstanding = _je_outstanding(row.journal_entry, claim.customer)
			pe.append(
				"references",
				{
					"reference_doctype": "Journal Entry",
					"reference_name": row.journal_entry,
					"total_amount": flt(row.allocated_amount) or flt(row.claim_amount),
					"outstanding_amount": outstanding if outstanding is not None else amount,
					"allocated_amount": amount,
					# set explicitly: Marley's PE validate only links a claim when the coverage JE carries
					# `insurance_coverage`, which its own invoice JE does not set
					"insurance_claim": claim.name,
					"insurance_claim_coverage": row.name,
				},
			)
		pe.setup_party_account_field()
		pe.set_missing_values()
		pe.flags.ignore_permissions = True
		pe.insert()
		pe.submit()
		return pe.name

	def on_cancel(self):
		for name in (self.payment_entries or "").split():
			if frappe.db.get_value("Payment Entry", name, "docstatus") == 1:
				frappe.get_doc("Payment Entry", name).cancel()
		self.db_set("status", "Cancelled")

	@frappe.whitelist()
	def import_lines(self):
		"""Read the attached CSV / XLSX into lines (manual remittance)."""
		if not self.import_file:
			frappe.throw(_("Attach a remittance file first"))
		from rcm_oman.claims.remittance_import import read_remittance_file

		self.set("items", [])
		for row in read_remittance_file(self.import_file):
			self.append("items", row)
		self.source = "Manual Import"
		self.save()
		return len(self.items)


def _je_outstanding(journal_entry, party):
	"""Open debit on the payer for a coverage Journal Entry (what a Payment Entry can still allocate)."""
	result = frappe.db.sql(
		"""
		SELECT SUM(debit_in_account_currency) - SUM(credit_in_account_currency)
		FROM `tabGL Entry`
		WHERE party_type = 'Customer' AND party = %s AND is_cancelled = 0
			AND ((voucher_type = 'Journal Entry' AND voucher_no = %s)
				OR (against_voucher_type = 'Journal Entry' AND against_voucher = %s))
		""",
		(party, journal_entry, journal_entry),
	)
	return flt(result[0][0]) if result and result[0][0] is not None else None
