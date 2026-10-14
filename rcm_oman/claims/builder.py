"""Build the canonical ClaimSubmission from a Marley Insurance Claim."""

import frappe
from frappe.utils import flt

from rcm_oman.canonical import Claim, ClaimSubmission, ServiceLine, group_claim_rows
from rcm_oman.claims.validation import service_date
from rcm_oman.utils import code_of, member_from_patient, party_for


def _licence(practitioner):
	if not practitioner:
		return None
	return frappe.db.get_value("Healthcare Practitioner", practitioner, "moh_licence_no")


def _approval_number(par):
	if not par:
		return None
	return frappe.db.get_value("Prior Authorization Request", par, "approval_number")


def _coverage_info(coverage):
	return (
		frappe.db.get_value(
			"Patient Insurance Coverage",
			coverage,
			["qty", "item_code", "encounter_type", "insurance_policy"],
			as_dict=True,
		)
		or frappe._dict()
	)


def build_service_line(row):
	cov = _coverage_info(row.insurance_coverage)
	gross = flt(row.sales_invoice_item_amount) or flt(row.claim_amount)
	description = row.medical_code_description or (
		frappe.get_cached_value("Item", row.item_code, "item_name") if row.item_code else None
	)
	return ServiceLine(
		line_id=row.name,
		service_date=str(service_date(row)),
		code_type="Service",
		code=code_of(row.code_value) or row.item_code,
		description=(description or "")[:140] or None,
		qty=flt(cov.qty) or 1,
		gross=round(gross, 3),
		patient_share=round(max(gross - flt(row.claim_amount), 0), 3),
		net=round(flt(row.claim_amount), 3),
		authorization=_approval_number(row.get("prior_authorization")),
		practitioner_licence=_licence(row.get("practitioner")),
	)


def build_submission(claim):
	party = party_for(claim.insurance_payor, claim.get("facility_licence"))
	rows = [r for r in claim.coverages if r.status not in ("Cancelled",)]
	claims = []
	original_ids = _original_external_ids(claim)
	for (patient, invoice), group in group_claim_rows([r.as_dict() for r in rows]):
		docs = [r for r in rows if r.name in {g["name"] for g in group}]
		first = docs[0]
		cov = _coverage_info(first.insurance_coverage)
		dates = sorted(str(service_date(r)) for r in docs if service_date(r))
		dx = []
		for r in docs:
			for code in (r.get("diagnosis_codes") or "").split(","):
				code = code.strip()
				if code and code not in dx:
					dx.append(code)
		claims.append(
			Claim(
				claim_key=f"{claim.name}/{invoice}",
				party=party,
				member=member_from_patient(patient, cov.insurance_policy or claim.get("insurance_policy")),
				encounter_type=cov.encounter_type or "Outpatient",
				encounter_start=dates[0] if dates else None,
				encounter_end=dates[-1] if dates else None,
				diagnosis_codes=dx,
				practitioner_licence=_licence(first.get("practitioner")),
				resubmission_of=original_ids.get(first.insurance_coverage),
				resubmission_type=claim.get("resubmission_type") or None,
				lines=[build_service_line(r) for r in docs],
			)
		)
	return ClaimSubmission(reference=claim.name, party=party, claims=claims)


def _original_external_ids(claim):
	if not claim.get("resubmission_of"):
		return {}
	rows = frappe.get_all(
		"Insurance Claim Coverage",
		filters={"parent": claim.resubmission_of},
		fields=["insurance_coverage", "external_claim_id"],
	)
	return {r.insurance_coverage: r.external_claim_id for r in rows if r.external_claim_id}
