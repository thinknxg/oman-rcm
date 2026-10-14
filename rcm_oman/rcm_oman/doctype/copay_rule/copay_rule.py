# Copyright (c) 2026, Kreatao and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class CopayRule(Document):
	def validate(self):
		if self.valid_from and self.valid_till and getdate(self.valid_till) < getdate(self.valid_from):
			frappe.throw(_("Valid Till cannot be before Valid From"))
		if self.copay_type in ("Percent", "Percent with Cap") and not 0 <= flt(self.copay_percent) <= 100:
			frappe.throw(_("Copay % must be between 0 and 100"))
		if self.copay_type == "Fixed" and flt(self.copay_fixed) <= 0:
			frappe.throw(_("Enter the fixed copay amount"))
		if self.copay_type == "Percent with Cap" and flt(self.max_patient_share) <= 0:
			frappe.throw(_("Enter the maximum patient share"))
		for field in ("copay_fixed", "max_patient_share", "min_patient_share", "deductible_per_line"):
			if flt(self.get(field)) < 0:
				frappe.throw(_("{0} cannot be negative").format(self.meta.get_label(field)))
		# keep only the target field that matches `applies_to`
		if self.applies_to != "Item":
			self.item_code = None
		if self.applies_to != "Item Group":
			self.item_group = None
		if self.applies_to != "Template":
			self.template_dt = None
