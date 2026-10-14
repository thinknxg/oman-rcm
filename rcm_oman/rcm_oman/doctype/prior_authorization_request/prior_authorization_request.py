# Copyright (c) 2026, Kreatao and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, today

from rcm_oman.canonical import AuthRequest, ServiceLine, to_dict
from rcm_oman.channel import DHAMANI, MANUAL, resolve_channel
from rcm_oman.transport import get_transport
from rcm_oman.utils import code_of, member_from_patient, party_for


class PriorAuthorizationRequest(Document):
	def validate(self):
		if not self.items:
			frappe.throw(_("Add at least one item to authorise"))
		for item in self.items:
			if item.insurance_coverage and not flt(item.requested_amount):
				item.requested_amount = flt(
					frappe.db.get_value(
						"Patient Insurance Coverage", item.insurance_coverage, "coverage_amount"
					)
				)
		self.requested_amount = sum(flt(i.requested_amount) for i in self.items)
		if self.docstatus == 0:
			self.status = "Draft"
			self.channel, _context, _reason = resolve_channel(
				self.insurance_payor, self.company, self.branch, on_date=self.posting_date
			)

	def before_submit(self):
		self.status = "Pending"

	def on_submit(self):
		if self.channel == DHAMANI:
			self.send()
		else:
			frappe.msgprint(
				_("Manual channel: send this request to the payer, then use Record Decision."),
				indicator="blue",
				alert=True,
			)

	def on_cancel(self):
		self.db_set("status", "Cancelled")
		transport = get_transport()
		if self.channel == DHAMANI and self.payer_reference and transport:
			_channel, context, _ = resolve_channel(self.insurance_payor, self.company, self.branch)
			transport.send(
				"Cancellation",
				{
					"reference": self.name,
					"kind": "Prior Authorization",
					"payer_reference": self.payer_reference,
				},
				self.doctype,
				self.name,
				context,
			)

	def build_request(self, facility_licence):
		lines = []
		for item in self.items:
			code = code_of(item.code_value) or item.item_code
			lines.append(
				ServiceLine(
					line_id=item.name,
					service_date=str(self.posting_date or today()),
					code_type="Service",
					code=code,
					description=frappe.get_cached_value("Item", item.item_code, "item_name")
					if item.item_code
					else None,
					qty=flt(item.qty) or 1,
					gross=flt(item.requested_amount),
					patient_share=0,
					net=flt(item.requested_amount),
				)
			)
		practitioner_licence = (
			frappe.db.get_value("Healthcare Practitioner", self.practitioner, "moh_licence_no")
			if self.practitioner
			else None
		)
		return AuthRequest(
			reference=self.name,
			party=party_for(self.insurance_payor, facility_licence),
			member=member_from_patient(self.patient, self.insurance_policy),
			encounter_type=self.encounter_type or "Outpatient",
			is_retroactive=bool(self.is_retroactive),
			diagnosis_codes=[code_of(self.diagnosis_code)] if self.diagnosis_code else [],
			clinical_notes=self.clinical_notes,
			practitioner_licence=practitioner_licence,
			lines=lines,
		)

	@frappe.whitelist()
	def send(self):
		transport = get_transport()
		channel, context, reason = resolve_channel(self.insurance_payor, self.company, self.branch)
		if channel == MANUAL or not transport:
			self.db_set("channel", MANUAL)
			frappe.msgprint(_("Sent to the manual queue: {0}").format(reason or ""), alert=True)
			return
		request = self.build_request(context.get("facility_licence"))
		transport.send("Prior Authorization", to_dict(request), self.doctype, self.name, context)
		self.db_set("status", "Pending")

	@frappe.whitelist()
	def switch_to_manual(self):
		if self.status not in ("Pending", "Error", "Draft"):
			frappe.throw(_("Only pending requests can be switched to manual"))
		self.db_set("channel", MANUAL)
		self.add_comment("Info", _("Switched to manual channel by {0}").format(frappe.session.user))
