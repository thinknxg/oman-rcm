"""Find the clinical encounter behind a billed service, for diagnosis codes and the practitioner."""

import frappe
from frappe.utils import getdate

# services that point to a Service Request, which points to the ordering encounter
SERVICE_REQUEST_LINKED = (
	"Lab Test",
	"Clinical Procedure",
	"Therapy Session",
	"Sample Collection",
	"Observation",
)


def _encounter(name):
	return frappe.get_doc("Patient Encounter", name) if name else None


def encounter_from_reference(reference_dt, reference_dn):
	if not reference_dt or not reference_dn or not frappe.db.exists(reference_dt, reference_dn):
		return None
	if reference_dt == "Patient Encounter":
		return _encounter(reference_dn)
	if reference_dt == "Patient Appointment":
		return _encounter(
			frappe.db.get_value(
				"Patient Encounter", {"appointment": reference_dn, "docstatus": ("<", 2)}, "name"
			)
		)
	if reference_dt == "Service Request":
		ref_dt, ref_dn = frappe.db.get_value(
			"Service Request", reference_dn, ["order_reference_doctype", "order_reference_name"]
		)
		if ref_dt == "Patient Encounter":
			return _encounter(ref_dn)
		return None
	if reference_dt == "Inpatient Record":
		discharge, admission = frappe.db.get_value(
			"Inpatient Record", reference_dn, ["discharge_encounter", "admission_encounter"]
		)
		return _encounter(discharge or admission)
	if reference_dt in SERVICE_REQUEST_LINKED and frappe.get_meta(reference_dt).has_field("service_request"):
		sr = frappe.db.get_value(reference_dt, reference_dn, "service_request")
		if sr:
			return encounter_from_reference("Service Request", sr)
		if frappe.get_meta(reference_dt).has_field("appointment"):
			appt = frappe.db.get_value(reference_dt, reference_dn, "appointment")
			if appt:
				return encounter_from_reference("Patient Appointment", appt)
	return None


def latest_encounter(patient, on_date=None):
	filters = {"patient": patient, "docstatus": ("<", 2)}
	if on_date:
		filters["encounter_date"] = ("<=", getdate(on_date))
	return _encounter(
		frappe.db.get_value(
			"Patient Encounter", filters, "name", order_by="encounter_date desc, creation desc"
		)
	)


def encounter_for_coverage(coverage):
	"""coverage: Patient Insurance Coverage doc."""
	if not coverage.is_new():
		for dt in ("Patient Appointment", "Service Request", "Inpatient Record"):
			if not frappe.get_meta(dt).has_field("insurance_coverage"):
				continue
			name = frappe.db.get_value(dt, {"insurance_coverage": coverage.name}, "name")
			if name:
				enc = encounter_from_reference(dt, name)
				if enc:
					return enc
	return latest_encounter(coverage.patient, coverage.posting_date)


def encounter_for_claim_row(row):
	"""row: Insurance Claim Coverage child row."""
	si_item = None
	if row.sales_invoice and row.insurance_coverage:
		si_item = frappe.db.get_value(
			"Sales Invoice Item",
			{"parent": row.sales_invoice, "insurance_coverage": row.insurance_coverage},
			["reference_dt", "reference_dn"],
			as_dict=True,
		)
	if si_item:
		enc = encounter_from_reference(si_item.reference_dt, si_item.reference_dn)
		if enc:
			return enc
	if row.insurance_coverage:
		return encounter_for_coverage(frappe.get_doc("Patient Insurance Coverage", row.insurance_coverage))
	return latest_encounter(row.patient, row.sales_invoice_posting_date)


def diagnosis_code_values(encounter):
	"""Code Value record names on an encounter's codification table, primary first."""
	if not encounter:
		return []
	names = []
	for row in encounter.get("codification_table") or []:
		if row.get("code_value") and row.code_value not in names:
			names.append(row.code_value)
	return names


def diagnosis_codes(encounter):
	"""Actual diagnosis codes (e.g. ICD-10 'J20.9') on an encounter, primary first."""
	from rcm_oman.utils import code_of

	if not encounter:
		return []
	codes = []
	for row in encounter.get("codification_table") or []:
		code = row.get("code") or code_of(row.get("code_value"))
		if code and code not in codes:
			codes.append(code)
	return codes
