"""Patient / payer split on Marley's Patient Insurance Coverage.

Runs as a doc_event after Marley's own validate(), which has already loaded the coverage % and
discount from Item Insurance Eligibility and computed `amount`. We then apply the Copay Rule and
any prior-authorisation cap, and write the result back into Marley's own fields (`coverage`,
`coverage_amount`, `patient_payable`) so invoicing, the coverage journal entry and the claim all
use the final payer share without further changes to Marley.
"""

import frappe
from frappe.utils import flt, getdate, today
from frappe.utils.nestedset import get_ancestors_of

from rcm_oman.rules.copay import compute_split, select_rule
from rcm_oman.utils import encounter_type_of

RULE_FIELDS = [
	"name",
	"is_active",
	"priority",
	"valid_from",
	"valid_till",
	"applies_to",
	"item_group",
	"item_code",
	"template_dt",
	"encounter_type",
	"copay_type",
	"copay_percent",
	"copay_fixed",
	"max_patient_share",
	"min_patient_share",
	"deductible_per_line",
]


def get_rules(insurance_plan):
	if not insurance_plan:
		return []
	return frappe.get_all(
		"Copay Rule", filters={"insurance_plan": insurance_plan, "is_active": 1}, fields=RULE_FIELDS
	)


def item_group_chain(item_code):
	if not item_code:
		return []
	group = frappe.get_cached_value("Item", item_code, "item_group")
	if not group:
		return []
	return [group, *get_ancestors_of("Item Group", group)]


def find_source_document(coverage):
	if coverage.is_new():
		return None
	for dt in ("Inpatient Record", "Service Request", "Patient Appointment", "Patient Encounter"):
		if not frappe.get_meta(dt).has_field("insurance_coverage"):
			continue
		name = frappe.db.get_value(dt, {"insurance_coverage": coverage.name}, "name")
		if name:
			return frappe.get_doc(dt, name)
	return None


def set_medical_code(doc):
	"""Marley leaves code_system / code_value empty on coverages; claims need the service code.
	Take it from the Item Insurance Eligibility, else from the service template's codification."""
	if doc.get("code_value"):
		return
	code_system = code_value = None
	if doc.get("item_eligibility"):
		code_system, code_value = frappe.db.get_value(
			"Item Insurance Eligibility", doc.item_eligibility, ["code_system", "code_value"]
		) or (None, None)
	if not code_value and doc.get("template_dt") and doc.get("template_dn"):
		if frappe.get_meta(doc.template_dt).has_field("codification_table"):
			row = frappe.db.get_value(
				"Codification Table",
				{"parenttype": doc.template_dt, "parent": doc.template_dn},
				["code_system", "code_value"],
				as_dict=True,
				order_by="idx asc",
			)
			if row:
				code_system, code_value = row.code_system, row.code_value
	if code_value:
		doc.code_value = code_value
		doc.code_system = code_system or frappe.db.get_value("Code Value", code_value, "code_system")
		doc.code_description = frappe.db.get_value("Code Value", code_value, "display")


def correct_item_only_eligibility(doc):
	"""Marley 16.6.x: for a coverage without a service template, get_insurance_eligibility() also
	matches every item-only eligibility on the plan (empty template_dt == empty template_dt), so an
	item can pick up another item's coverage % and approval mode. Re-resolve by item_code."""
	if doc.get("template_dt") or not doc.get("item_code") or not doc.get("item_eligibility"):
		return
	if frappe.db.get_value("Item Insurance Eligibility", doc.item_eligibility, "item_code") == doc.item_code:
		return
	on_date = getdate(doc.posting_date or today())
	rows = frappe.get_all(
		"Item Insurance Eligibility",
		filters={
			"insurance_plan": doc.insurance_plan,
			"item_code": doc.item_code,
			"is_active": 1,
			"valid_from": ("<=", on_date),
		},
		fields=["name", "mode_of_approval", "coverage", "discount", "valid_till"],
		order_by="valid_from desc",
	)
	rows = [r for r in rows if not r.valid_till or getdate(r.valid_till) >= on_date]
	if not rows:
		doc.item_eligibility = None
		doc.coverage = 0
		doc.status = "Draft"
		return
	e = rows[0]
	doc.item_eligibility, doc.mode_of_approval = e.name, e.mode_of_approval
	doc.coverage, doc.discount = e.coverage, e.discount
	doc.discount_amount = flt(doc.price_list_rate) * flt(doc.discount) * 0.01 * flt(doc.qty)
	doc.amount = flt(doc.price_list_rate) * flt(doc.qty) - flt(doc.discount_amount)
	if e.mode_of_approval == "Manual" and doc.status == "Approved":
		doc.status = "Draft"
	elif e.mode_of_approval == "Automatic" and flt(e.coverage) > 0:
		doc.status = "Approved"


def apply_patient_share(doc, method=None):
	# also runs inside submit(): Frappe re-validates with docstatus=1 and Marley recomputes the split
	submitting = doc.docstatus == 1 and getattr(doc, "_action", None) == "submit"
	if (doc.docstatus != 0 and not submitting) or doc.status not in ("Draft", "Approved"):
		return
	correct_item_only_eligibility(doc)
	set_medical_code(doc)
	amount = flt(doc.amount)
	if amount <= 0:
		return

	source = find_source_document(doc)
	if source is not None:
		doc.encounter_type = encounter_type_of(source)
	doc.encounter_type = doc.encounter_type or "Outpatient"

	rule = select_rule(
		get_rules(doc.insurance_plan),
		item_code=doc.item_code,
		item_groups=item_group_chain(doc.item_code),
		template_dt=doc.template_dt,
		encounter_type=doc.encounter_type,
		on_date=str(doc.posting_date) if doc.posting_date else None,
	)

	auth_cap = None
	if doc.get("prior_authorization") and doc.get("authorized_amount") is not None:
		par_status = frappe.db.get_value("Prior Authorization Request", doc.prior_authorization, "status")
		if par_status in ("Approved", "Partially Approved"):
			auth_cap = flt(doc.authorized_amount)

	split = compute_split(amount, doc.coverage, rule=rule, authorized_cap=auth_cap)

	doc.copay_rule = rule.get("name") if rule else None
	doc.deductible_amount = split.deductible
	doc.copay_amount = split.copay
	doc.coverage_amount = split.payer_share
	doc.patient_payable = split.patient_payable
	# Marley's Sales Invoice applies `coverage` % to the line amount: keep it consistent
	doc.coverage = split.effective_coverage_percent
