"""Denial cases: one per denied (or short-paid) claim line, worked to resubmission, write-off,
patient re-bill or recovery. Write-off and re-bill post a Journal Entry against the coverage
transfer Journal Entry that Marley posted when the invoice was submitted."""

import frappe
from frappe import _
from frappe.utils import add_days, flt, today

from rcm_oman.utils import int_setting

OPEN_STATES = ("Open", "In Progress", "Resubmitted", "Appealed")


def open_case(claim, row, denied_amount, denial_code=None, reason=None):
	"""Create (or update) the open case for a claim row."""
	if flt(denied_amount) <= 0:
		return None
	existing = frappe.db.get_value(
		"Denial Case",
		{"insurance_claim": claim.name, "claim_coverage": row.name, "status": ("in", OPEN_STATES)},
		"name",
	)
	if existing:
		case = frappe.get_doc("Denial Case", existing)
	else:
		case = frappe.new_doc("Denial Case")
		case.update(
			{
				"insurance_claim": claim.name,
				"claim_coverage": row.name,
				"insurance_coverage": row.insurance_coverage,
				"patient": row.patient,
				"insurance_payor": claim.insurance_payor,
				"company": claim.company,
				"branch": claim.get("branch"),
				"claimed_amount": row.claim_amount,
				"status": "Open",
				"due_date": add_days(today(), int_setting("denial_case_due_days", 14)),
			}
		)
	case.denied_amount = flt(denied_amount, 3)
	case.denial_code = denial_code or case.denial_code
	case.denial_reason = reason or case.denial_reason
	if case.denial_code and not case.action:
		patient_resp, resubmittable = frappe.db.get_value(
			"Denial Code", case.denial_code, ["patient_responsible", "resubmittable"]
		) or (0, 1)
		case.action = "Rebill Patient" if patient_resp else ("Resubmit" if resubmittable else "Write Off")
	case.save(ignore_permissions=True)
	return case


def _coverage_journal_entry(case):
	return frappe.db.get_value("Insurance Claim Coverage", case.claim_coverage, "journal_entry")


def _payor_accounts(case):
	from healthcare.healthcare.doctype.insurance_payor.insurance_payor import (
		get_insurance_payor_details,
		get_insurance_payor_expense_account,
	)

	details = get_insurance_payor_details(case.insurance_payor, case.company)
	return details, get_insurance_payor_expense_account


def _post_adjustment(case, amount, debit_row, remark):
	"""Credit the payer receivable (against the coverage JE), debit `debit_row`."""
	details, _expense = _payor_accounts(case)
	je_ref = _coverage_journal_entry(case)
	cost_center = frappe.get_cached_value("Company", case.company, "cost_center")
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = case.company
	je.posting_date = today()
	je.user_remark = remark
	je.append(
		"accounts",
		{
			"account": details.get("receivable_account"),
			"party_type": "Customer",
			"party": details.get("party"),
			"credit_in_account_currency": amount,
			"reference_type": "Journal Entry" if je_ref else None,
			"reference_name": je_ref,
			"cost_center": cost_center,
		},
	)
	debit_row.setdefault("cost_center", cost_center)
	debit_row["debit_in_account_currency"] = amount
	je.append("accounts", debit_row)
	if case.get("branch") and je.meta.has_field("branch"):
		je.branch = case.branch
		for acc in je.accounts:
			if acc.meta.has_field("branch"):
				acc.branch = case.branch
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	return je


def _bump_claim_row(case, fieldname, amount):
	claim = frappe.get_doc("Insurance Claim", case.insurance_claim)
	for row in claim.coverages:
		if row.name == case.claim_coverage:
			row.set(fieldname, flt(row.get(fieldname)) + amount)
	claim.flags.ignore_validate_update_after_submit = True
	claim.save(ignore_permissions=True)


def _open_amount(case):
	return (
		flt(case.denied_amount)
		- flt(case.recovered_amount)
		- flt(case.written_off_amount)
		- flt(case.rebilled_amount)
	)


@frappe.whitelist()
def write_off(name, amount=None, remark=None):
	case = frappe.get_doc("Denial Case", name)
	case.check_permission("write")
	amount = flt(amount) or _open_amount(case)
	if amount <= 0:
		frappe.throw(_("Nothing left to write off"))
	from healthcare.healthcare.doctype.insurance_payor.insurance_payor import (
		get_insurance_payor_expense_account,
	)

	expense = get_insurance_payor_expense_account(case.insurance_payor, case.company)
	je = _post_adjustment(
		case, amount, {"account": expense}, remark or _("Claim denial write-off {0}").format(case.name)
	)
	case.written_off_amount = flt(case.written_off_amount) + amount
	case.journal_entry = je.name
	case.status = "Written Off"
	case.save(ignore_permissions=True)
	_bump_claim_row(case, "written_off_amount", amount)
	return je.name


@frappe.whitelist()
def rebill_patient(name, amount=None, remark=None):
	case = frappe.get_doc("Denial Case", name)
	case.check_permission("write")
	amount = flt(amount) or _open_amount(case)
	if amount <= 0:
		frappe.throw(_("Nothing left to re-bill"))
	customer = frappe.db.get_value("Patient", case.patient, "customer")
	if not customer:
		frappe.throw(_("Patient {0} has no linked Customer").format(case.patient))
	from erpnext.accounts.party import get_party_account

	receivable = get_party_account("Customer", customer, case.company)
	je = _post_adjustment(
		case,
		amount,
		{"account": receivable, "party_type": "Customer", "party": customer},
		remark or _("Denied by payer, re-billed to patient ({0})").format(case.name),
	)
	case.rebilled_amount = flt(case.rebilled_amount) + amount
	case.journal_entry = je.name
	case.status = "Rebilled to Patient"
	case.save(ignore_permissions=True)
	_bump_claim_row(case, "rebilled_amount", amount)
	return je.name


def mark_recovered(insurance_coverage, amount, claim_name):
	"""Called when a resubmitted line is paid: close the original case."""
	for case_name in frappe.get_all(
		"Denial Case",
		filters={"insurance_coverage": insurance_coverage, "status": ("in", OPEN_STATES)},
		pluck="name",
	):
		case = frappe.get_doc("Denial Case", case_name)
		recovered = min(flt(amount), _open_amount(case))
		if recovered <= 0:
			continue
		case.recovered_amount = flt(case.recovered_amount) + recovered
		case.status = "Recovered" if _open_amount(case) <= 0.0005 else case.status
		case.add_comment("Info", _("Recovered {0} via {1}").format(recovered, claim_name))
		case.save(ignore_permissions=True)
		amount = flt(amount) - recovered


def remind_overdue_cases():
	overdue = frappe.get_all(
		"Denial Case",
		filters={
			"status": ("in", ["Open", "In Progress"]),
			"due_date": ("<", today()),
			"assigned_to": ("is", "set"),
		},
		fields=["name", "assigned_to", "insurance_claim", "denied_amount"],
	)
	by_user = {}
	for c in overdue:
		by_user.setdefault(c.assigned_to, []).append(c)
	for user, cases in by_user.items():
		frappe.sendmail(
			recipients=[user],
			subject=_("{0} overdue denial cases").format(len(cases)),
			message="<ul>"
			+ "".join(f"<li>{c.name} — {c.insurance_claim} — {c.denied_amount}</li>" for c in cases)
			+ "</ul>",
		)
