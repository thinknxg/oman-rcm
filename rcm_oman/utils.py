import frappe
from frappe.utils import cint


def settings():
	return frappe.get_cached_doc("RCM Settings")


def setting(fieldname, default=None):
	value = frappe.db.get_single_value("RCM Settings", fieldname)
	return default if value in (None, "") else value


def has_role(role, user=None):
	return role in frappe.get_roles(user or frappe.session.user)


def member_from_patient(patient, policy=None):
	"""Canonical Member dict for a patient and (optionally) a Patient Insurance Policy."""
	from rcm_oman.canonical import Member

	p = frappe.db.get_value(
		"Patient", patient, ["name", "patient_name", "dob", "sex", "id_type", "civil_id"], as_dict=True
	)
	member = Member(
		patient_id=p.name,
		id_type=p.id_type,
		id_number=p.civil_id,
		name=p.patient_name,
		dob=str(p.dob) if p.dob else None,
		gender=p.sex,
	)
	if policy:
		pol = frappe.db.get_value(
			"Patient Insurance Policy", policy, ["policy_number", "dhamani_member_id"], as_dict=True
		)
		if pol:
			member.policy_number = pol.policy_number
			member.member_id = pol.dhamani_member_id
	return member


def party_for(insurance_payor, facility_licence):
	from rcm_oman.canonical import Party

	party = Party(payer_name=insurance_payor)
	if insurance_payor:
		party.payer_code = frappe.db.get_value("Insurance Payor", insurance_payor, "dhamani_payer_code")
	if facility_licence:
		lic = frappe.db.get_value(
			"Facility Licence", facility_licence, ["moh_licence_no", "dhamani_provider_code"], as_dict=True
		)
		if lic:
			party.facility_licence = lic.moh_licence_no
			party.provider_code = lic.dhamani_provider_code
	return party


def encounter_type_of(doc):
	"""Outpatient / Inpatient / Emergency from a clinical document."""
	if not doc:
		return "Outpatient"
	if doc.get("doctype") == "Inpatient Record" or doc.get("inpatient_record"):
		return "Inpatient"
	appointment_type = doc.get("appointment_type") or ""
	if "emergency" in appointment_type.lower():
		return "Emergency"
	return "Outpatient"


def ensure_denial_code(code, reason=None, source="Dhamani"):
	if not code:
		return None
	if not frappe.db.exists("Denial Code", code):
		frappe.get_doc(
			{
				"doctype": "Denial Code",
				"code": code,
				"description": (reason or code)[:140],
				"source": source,
				"category": "Other",
				"resubmittable": 1,
			}
		).insert(ignore_permissions=True)
	return code


def int_setting(fieldname, default):
	return cint(setting(fieldname, default)) or default


def code_of(code_value_name):
	"""The actual code (e.g. 'J20.9', '99213') behind a Marley Code Value record (named by hash)."""
	if not code_value_name:
		return None
	return frappe.db.get_value("Code Value", code_value_name, "code_value") or code_value_name
