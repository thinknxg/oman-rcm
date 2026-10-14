# Copyright (c) 2026, Kreatao and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class DenialCase(Document):
	def validate(self):
		for field in ("recovered_amount", "written_off_amount", "rebilled_amount"):
			if flt(self.get(field)) < 0:
				frappe.throw(_("{0} cannot be negative").format(self.meta.get_label(field)))
		settled = flt(self.recovered_amount) + flt(self.written_off_amount) + flt(self.rebilled_amount)
		if settled > flt(self.denied_amount) + 0.0005:
			frappe.throw(_("Recovered, written off and re-billed amounts exceed the denied amount"))
		if self.status == "Open" and self.assigned_to:
			self.status = "In Progress"

	@frappe.whitelist()
	def resubmit(self, resubmission_type="Correction"):
		claim = frappe.get_doc("Insurance Claim", self.insurance_claim)
		return claim.make_resubmission(resubmission_type)

	@frappe.whitelist()
	def write_off(self, amount=None, remark=None):
		from rcm_oman.denials import write_off

		return write_off(self.name, amount, remark)

	@frappe.whitelist()
	def rebill_patient(self, amount=None, remark=None):
		from rcm_oman.denials import rebill_patient

		return rebill_patient(self.name, amount, remark)
