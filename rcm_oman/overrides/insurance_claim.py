"""Insurance Claim extended for Oman: branch / facility licence, pre-submission validation,
Dhamani or manual dispatch, partial payer approvals, resubmission and information replies.

Marley's claim treats a line as all-or-nothing (Approved = full claim amount). Payers adjudicate
partially, so a line the payer has adjudicated carries `payer_approved_amount`; after Marley's
own before_update_after_submit we re-derive approved / rejected / status from it.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, today

from healthcare.healthcare.doctype.insurance_claim.insurance_claim import InsuranceClaim
from rcm_oman.canonical import to_dict
from rcm_oman.channel import DHAMANI, MANUAL, resolve_channel
from rcm_oman.claims.validation import format_report, has_errors, validate_claim
from rcm_oman.transport import get_transport
from rcm_oman.utils import setting

TOLERANCE = 0.0005


class RCMInsuranceClaim(InsuranceClaim):
	# ------------------------------------------------------------------ draft
	def validate(self):
		super().validate()
		self.set_branch_and_licence()
		if self.docstatus == 0:
			self.rcm_channel, _context, _reason = resolve_channel(
				self.insurance_payor, self.company, self.get("branch"), on_date=self.posting_date
			)
			self.submission_status = "Not Sent"

	def set_branch_and_licence(self):
		if not self.get("branch"):
			for row in self.coverages:
				branch = frappe.db.get_value("Patient Insurance Coverage", row.insurance_coverage, "branch")
				if branch:
					self.branch = branch
					break
		if self.get("branch") and not self.get("facility_licence"):
			from his_oman.licensing import get_facility_licence

			self.facility_licence = get_facility_licence(self.branch, self.company, self.posting_date)

	def validate_existing_insurance_claims(self):
		"""Marley blocks a coverage already on a Submitted / Approved / Completed claim line. A
		resubmission legitimately re-claims the denied remainder of lines in its own claim chain."""
		if not self.get("resubmission_of"):
			return super().validate_existing_insurance_claims()
		chain = claim_chain(self.resubmission_of)
		coverages = [c.insurance_coverage for c in self.coverages]
		clashes = frappe.get_all(
			"Insurance Claim Coverage",
			filters={
				"parent": ("not in", [*chain, self.name or ""]),
				"status": ("in", ["Submitted", "Approved", "Completed"]),
				"insurance_coverage": ("in", coverages),
			},
			fields=["insurance_coverage", "parent"],
		)
		if clashes:
			frappe.throw(
				_("Coverage already claimed outside this resubmission chain: {0}").format(
					", ".join(f"{c.insurance_coverage} ({c.parent})" for c in clashes)
				)
			)

	@frappe.whitelist()
	def run_validation(self):
		issues = validate_claim(self, self.rcm_channel or MANUAL)
		self.validation_report = format_report(issues)
		return {"issues": issues, "report": self.validation_report}

	# ----------------------------------------------------------------- submit
	def before_submit(self):
		super().before_submit()
		issues = validate_claim(self, self.rcm_channel or MANUAL)
		self.validation_report = format_report(issues)
		if has_errors(issues) and int(setting("block_claim_on_validation_error", 1) or 0):
			frappe.throw(
				"<pre style='white-space:pre-wrap'>"
				+ frappe.utils.escape_html(self.validation_report)
				+ "</pre>",
				title=_("Claim failed pre-submission validation"),
			)

	def on_submit(self):
		super().on_submit()
		self.dispatch()

	def dispatch(self, force_manual=False):
		channel = MANUAL if force_manual else (self.rcm_channel or MANUAL)
		transport = get_transport()
		if channel == DHAMANI and transport:
			_channel, context, _reason = resolve_channel(
				self.insurance_payor, self.company, self.get("branch")
			)
			context["facility_licence"] = self.get("facility_licence") or context.get("facility_licence")
			from rcm_oman.claims.builder import build_submission

			message_type = "Resubmission" if self.get("resubmission_of") else "Claim"
			transport.send(message_type, to_dict(build_submission(self)), self.doctype, self.name, context)
			self.db_set({"submission_status": "Queued", "rcm_channel": DHAMANI})
		else:
			from rcm_oman.claims.pack import generate_manual_pack

			self.db_set("rcm_channel", MANUAL)
			generate_manual_pack(self.name)
			self.submission_status = frappe.db.get_value(self.doctype, self.name, "submission_status")

	# --------------------------------------------------------- after submit
	def before_update_after_submit(self):
		super().before_update_after_submit()
		self.apply_payer_amounts()

	def apply_payer_amounts(self):
		approved_total = rejected_total = paid_total = 0
		for row in self.coverages:
			if row.get("payer_adjudicated") and row.status in ("Approved", "Completed"):
				approved = min(flt(row.payer_approved_amount), flt(row.claim_amount))
				row.approved_amount = approved
				row.rejected_amount = flt(row.claim_amount) - approved
				row.status = "Completed" if flt(row.paid_amount) >= approved - TOLERANCE else "Approved"
				frappe.db.set_value(
					"Patient Insurance Coverage",
					row.insurance_coverage,
					{"approved_amount": row.approved_amount, "paid_amount": row.paid_amount},
					update_modified=False,
				)
			approved_total += flt(row.approved_amount)
			rejected_total += flt(row.rejected_amount)
			paid_total += flt(row.paid_amount)

		self.approved_amount = approved_total
		self.rejected_amount = rejected_total
		self.paid_amount = paid_total
		self.outstanding_amount = approved_total - paid_total
		all_decided = all(r.status in ("Completed", "Rejected", "Error", "Cancelled") for r in self.coverages)
		if all_decided and abs(self.outstanding_amount) <= TOLERANCE:
			self.status = (
				"Error"
				if abs(rejected_total - flt(self.insurance_claim_amount)) <= TOLERANCE
				else "Completed"
			)
		else:
			self.status = "Submitted"

		if paid_total > 0 and self.get("submission_status") not in ("Cancelled",):
			self.submission_status = "Paid" if self.status in ("Completed", "Error") else "Partly Paid"

	# ----------------------------------------------------------------- cancel
	def on_cancel(self):
		if hasattr(super(), "on_cancel"):
			super().on_cancel()
		transport = get_transport()
		if (
			self.get("rcm_channel") == DHAMANI
			and self.get("submission_status") not in ("Not Sent", "Queued")
			and transport
		):
			_channel, context, _reason = resolve_channel(
				self.insurance_payor, self.company, self.get("branch")
			)
			transport.send(
				"Cancellation",
				{
					"reference": self.name,
					"kind": "Claim",
					"external_claim_ids": sorted(
						{r.external_claim_id for r in self.coverages if r.get("external_claim_id")}
					),
				},
				self.doctype,
				self.name,
				context,
			)
		self.db_set("submission_status", "Cancelled")

	# ----------------------------------------------------------- actions
	@frappe.whitelist()
	def resend(self):
		"""Re-send after a platform rejection (data fixed) or switch back from manual."""
		self.check_permission("submit")
		if self.docstatus != 1:
			frappe.throw(_("Only submitted claims can be re-sent"))
		issues = validate_claim(self, DHAMANI)
		self.db_set("validation_report", format_report(issues))
		if has_errors(issues):
			frappe.throw(
				_("Fix validation errors first:<br>{0}").format(self.validation_report.replace("\n", "<br>"))
			)
		self.rcm_channel = DHAMANI
		self.dispatch()
		return self.submission_status

	@frappe.whitelist()
	def switch_to_manual(self):
		self.check_permission("submit")
		self.dispatch(force_manual=True)
		self.add_comment("Info", _("Switched to manual channel by {0}").format(frappe.session.user))
		return self.submission_status

	@frappe.whitelist()
	def reply_information(self, message, attachments=None):
		self.check_permission("submit")
		if not message:
			frappe.throw(_("Write a reply"))
		attachments = frappe.parse_json(attachments) if isinstance(attachments, str) else (attachments or [])
		files = []
		for url in attachments:
			f = frappe.db.get_value("File", {"file_url": url}, ["file_name", "file_url"], as_dict=True)
			if f:
				files.append({"name": f.file_name, "url": f.file_url})
		transport = get_transport()
		if self.get("rcm_channel") == DHAMANI and transport:
			_channel, context, _reason = resolve_channel(
				self.insurance_payor, self.company, self.get("branch")
			)
			transport.send(
				"Information Reply",
				{
					"reference": self.name,
					"external_claim_ids": sorted(
						{r.external_claim_id for r in self.coverages if r.get("external_claim_id")}
					),
					"message": message,
					"attachments": files,
				},
				self.doctype,
				self.name,
				context,
			)
			self.db_set("submission_status", "Sent")
		self.add_comment("Comment", _("Reply to payer: {0}").format(message))
		return self.submission_status

	@frappe.whitelist()
	def make_resubmission(self, resubmission_type="Correction", rows=None):
		"""Draft a corrected claim for denied amounts. `rows`: claim line names; default = every line
		with an open Denial Case."""
		self.check_permission("submit")
		rows_wanted = frappe.parse_json(rows) if isinstance(rows, str) else rows
		open_lines = set(
			frappe.get_all(
				"Denial Case",
				filters={"insurance_claim": self.name, "status": ("in", ["Open", "In Progress"])},
				pluck="claim_coverage",
			)
		)
		rows = []
		for row in self.coverages:
			if rows_wanted is not None and row.name not in rows_wanted:
				continue
			if rows_wanted is None and row.name not in open_lines:
				continue
			denied = (
				flt(row.claim_amount) - flt(row.payer_approved_amount) if row.get("payer_adjudicated") else 0
			)
			if row.status == "Rejected":
				denied = flt(row.claim_amount)
			denied -= flt(row.get("written_off_amount")) + flt(row.get("rebilled_amount"))
			if denied > TOLERANCE:
				rows.append((row, flt(denied, 3)))
		if not rows:
			frappe.throw(_("No denied lines with open denial cases to resubmit"))

		new = frappe.new_doc("Insurance Claim")
		for field in (
			"insurance_payor",
			"company",
			"customer",
			"patient",
			"insurance_policy",
			"insurance_plan",
			"policy_number",
			"inpatient_record",
			"code_system",
			"mode_of_payment",
			"posting_date_based_on",
			"from_date",
			"to_date",
			"branch",
			"facility_licence",
		):
			if self.meta.has_field(field):
				new.set(field, self.get(field))
		new.posting_date = today()
		credit_days = frappe.db.get_value(
			"Insurance Payor", self.insurance_payor, "insurance_claim_credit_days"
		)
		new.due_date = add_days(today(), int(credit_days or 45))
		new.resubmission_of = self.name
		new.resubmission_type = resubmission_type
		skip = {
			"name",
			"idx",
			"parent",
			"parentfield",
			"parenttype",
			"doctype",
			"status",
			"approved_amount",
			"rejected_amount",
			"paid_amount",
			"payment_error_reason",
			"external_claim_id",
			"payer_adjudicated",
			"payer_approved_amount",
			"denial_code",
			"written_off_amount",
			"rebilled_amount",
			"creation",
			"modified",
			"owner",
			"modified_by",
			"docstatus",
		}
		for row, denied in rows:
			data = {k: v for k, v in row.as_dict().items() if k not in skip}
			data["claim_amount"] = denied
			data["allocated_amount"] = denied
			data["status"] = "Draft"
			new.append("coverages", data)
		new.insert()

		for row, _denied in rows:
			for case in frappe.get_all(
				"Denial Case",
				filters={
					"insurance_claim": self.name,
					"claim_coverage": row.name,
					"status": ("in", ["Open", "In Progress"]),
				},
				pluck="name",
			):
				frappe.db.set_value(
					"Denial Case", case, {"status": "Resubmitted", "resubmission_claim": new.name}
				)
		return new.name


def claim_chain(claim_name):
	"""The claim and every claim it resubmits, back to the original."""
	chain = []
	while claim_name and claim_name not in chain:
		chain.append(claim_name)
		claim_name = frappe.db.get_value("Insurance Claim", claim_name, "resubmission_of")
	return chain
