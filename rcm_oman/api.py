import frappe

from rcm_oman import prior_auth


@frappe.whitelist()
def make_prior_authorization(coverages, practitioner=None, diagnosis_code=None, clinical_notes=None):
	coverages = frappe.parse_json(coverages) if isinstance(coverages, str) else coverages
	for name in coverages:
		frappe.has_permission("Patient Insurance Coverage", "read", name, throw=True)
	frappe.has_permission("Prior Authorization Request", "create", throw=True)
	return prior_auth.make_prior_authorization(coverages, practitioner, diagnosis_code, clinical_notes).name
