import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


# Marley 16.6.x ships insurance_claim.json with `mode_of_payment_section` and `column_break_133`
# defined twice, so Frappe's field validation rejects any customisation of Insurance Claim.
# Our fields are valid; skip the doctype-wide re-validation for that DocType only.
SKIP_VALIDATION_FOR = {"Insurance Claim"}


def apply_custom_fields(fields_by_doctype):
	normal = {dt: f for dt, f in fields_by_doctype.items() if dt not in SKIP_VALIDATION_FOR}
	skipped = {dt: f for dt, f in fields_by_doctype.items() if dt in SKIP_VALIDATION_FOR}
	create_custom_fields(normal, update=True)
	if skipped:
		create_custom_fields(skipped, ignore_validate=True, update=True)


ROLES = ["RCM Manager", "RCM User"]

CLAIM_SUBMISSION_STATUSES = (
	"Not Sent\nQueued\nSent\nAccepted\nRejected by Platform\nInformation Requested\n"
	"Adjudicated\nPartly Paid\nPaid\nManual Pack Generated\nCancelled"
)

# Generic internal codes; load the Dhamani denial-code list on top once the FSA spec is issued.
DEFAULT_DENIAL_CODES = [
	("ELIG-01", "Member not eligible on date of service", "Eligibility", 1, 0),
	("ELIG-02", "Policy expired or terminated", "Eligibility", 1, 0),
	("AUTH-01", "Prior authorisation missing", "Authorization", 0, 1),
	("AUTH-02", "Service exceeds authorised quantity or amount", "Authorization", 0, 1),
	("AUTH-03", "Authorisation expired", "Authorization", 0, 1),
	("CODE-01", "Invalid or missing diagnosis code", "Coding", 0, 1),
	("CODE-02", "Service code not covered by contract", "Contractual", 1, 1),
	("CODE-03", "Diagnosis does not support the service", "Clinical", 0, 1),
	("DUP-01", "Duplicate claim", "Duplicate", 0, 0),
	("PRICE-01", "Price exceeds contracted tariff", "Contractual", 0, 1),
	(
		"EXCL-01",
		"Excluded under the policy (e.g. pre-existing condition, travel check-up)",
		"Contractual",
		1,
		0,
	),
	("TIME-01", "Submitted after filing deadline", "Timely Filing", 0, 0),
	("TECH-01", "Technical rejection by platform", "Technical", 0, 1),
	("LIC-01", "Practitioner or facility licence invalid", "Technical", 0, 1),
]


def get_custom_fields():
	return {
		"Insurance Payor": [
			{
				"fieldname": "rcm_section",
				"label": "Dhamani",
				"fieldtype": "Section Break",
				"insert_after": "code_system",
			},
			{
				"fieldname": "dhamani_payer_code",
				"label": "Dhamani Payer Code",
				"fieldtype": "Data",
				"insert_after": "rcm_section",
				"unique": 1,
			},
			{
				"fieldname": "is_tpa",
				"label": "Is TPA",
				"fieldtype": "Check",
				"insert_after": "dhamani_payer_code",
			},
			{
				"fieldname": "parent_payor",
				"label": "Insurer behind TPA",
				"fieldtype": "Link",
				"options": "Insurance Payor",
				"insert_after": "is_tpa",
				"depends_on": "is_tpa",
			},
		],
		"Insurance Payor Contract": [
			{
				"fieldname": "rcm_channel",
				"label": "Insurance Channel",
				"fieldtype": "Select",
				"options": "Manual\nDhamani\nHybrid",
				"default": "Manual",
				"insert_after": "default_price_list",
				"allow_on_submit": 1,
				"in_list_view": 1,
				"description": "Dhamani: direct, queued while the link is down. Hybrid: direct, falls back to manual when the link is down. Manual: payer not on Dhamani.",
			},
			{
				"fieldname": "resubmission_days",
				"label": "Resubmission Window (Days)",
				"fieldtype": "Int",
				"insert_after": "rcm_channel",
				"allow_on_submit": 1,
			},
			{
				"fieldname": "manual_submission_email",
				"label": "Manual Claims Email",
				"fieldtype": "Data",
				"options": "Email",
				"insert_after": "resubmission_days",
				"allow_on_submit": 1,
			},
		],
		"Patient Insurance Policy": [
			{
				"fieldname": "rcm_verification_section",
				"label": "Eligibility",
				"fieldtype": "Section Break",
				"insert_after": "policy_expiry_date",
			},
			{
				"fieldname": "dhamani_member_id",
				"label": "Dhamani Member ID",
				"fieldtype": "Data",
				"insert_after": "rcm_verification_section",
				"allow_on_submit": 1,
			},
			{
				"fieldname": "verification_status",
				"label": "Verification Status",
				"fieldtype": "Select",
				"options": "Not Verified\nVerified\nUnverified Override\nNot Eligible",
				"default": "Not Verified",
				"insert_after": "dhamani_member_id",
				"allow_on_submit": 1,
				"read_only": 1,
				"in_list_view": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "rcm_verification_cb",
				"fieldtype": "Column Break",
				"insert_after": "verification_status",
			},
			{
				"fieldname": "last_verified_on",
				"label": "Last Verified On",
				"fieldtype": "Datetime",
				"insert_after": "rcm_verification_cb",
				"allow_on_submit": 1,
				"read_only": 1,
			},
			{
				"fieldname": "last_eligibility_check",
				"label": "Last Eligibility Check",
				"fieldtype": "Link",
				"options": "Eligibility Check",
				"insert_after": "last_verified_on",
				"allow_on_submit": 1,
				"read_only": 1,
			},
		],
		"Patient Insurance Coverage": [
			{
				"fieldname": "rcm_split_section",
				"label": "Patient Share",
				"fieldtype": "Section Break",
				"insert_after": "patient_payable",
			},
			{
				"fieldname": "encounter_type",
				"label": "Encounter Type",
				"fieldtype": "Select",
				"options": "Outpatient\nInpatient\nEmergency",
				"default": "Outpatient",
				"insert_after": "rcm_split_section",
			},
			{
				"fieldname": "copay_rule",
				"label": "Copay Rule",
				"fieldtype": "Link",
				"options": "Copay Rule",
				"insert_after": "encounter_type",
				"read_only": 1,
			},
			{"fieldname": "rcm_split_cb", "fieldtype": "Column Break", "insert_after": "copay_rule"},
			{
				"fieldname": "deductible_amount",
				"label": "Deductible",
				"fieldtype": "Currency",
				"insert_after": "rcm_split_cb",
				"read_only": 1,
			},
			{
				"fieldname": "copay_amount",
				"label": "Copay",
				"fieldtype": "Currency",
				"insert_after": "deductible_amount",
				"read_only": 1,
			},
			{"fieldname": "rcm_split_cb2", "fieldtype": "Column Break", "insert_after": "copay_amount"},
			{
				"fieldname": "prior_authorization",
				"label": "Prior Authorization",
				"fieldtype": "Link",
				"options": "Prior Authorization Request",
				"insert_after": "rcm_split_cb2",
				"read_only": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "authorized_amount",
				"label": "Authorised Payer Amount",
				"fieldtype": "Currency",
				"insert_after": "prior_authorization",
				"read_only": 1,
				"allow_on_submit": 1,
			},
		],
		"Insurance Claim": [
			{
				"fieldname": "rcm_submission_section",
				"label": "Submission",
				"fieldtype": "Section Break",
				"insert_after": "outstanding_amount",
			},
			{
				"fieldname": "rcm_channel",
				"label": "Channel",
				"fieldtype": "Select",
				"options": "Dhamani\nManual",
				"insert_after": "rcm_submission_section",
				"read_only": 1,
				"in_list_view": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "submission_status",
				"label": "Submission Status",
				"fieldtype": "Select",
				"options": CLAIM_SUBMISSION_STATUSES,
				"default": "Not Sent",
				"insert_after": "rcm_channel",
				"read_only": 1,
				"allow_on_submit": 1,
				"in_list_view": 1,
				"in_standard_filter": 1,
			},
			{
				"fieldname": "submitted_on",
				"label": "Submitted to Payer On",
				"fieldtype": "Datetime",
				"insert_after": "submission_status",
				"read_only": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "payer_batch_reference",
				"label": "Payer Batch Reference",
				"fieldtype": "Data",
				"insert_after": "submitted_on",
				"read_only": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "rcm_submission_cb",
				"fieldtype": "Column Break",
				"insert_after": "payer_batch_reference",
			},
			{
				"fieldname": "resubmission_of",
				"label": "Resubmission Of",
				"fieldtype": "Link",
				"options": "Insurance Claim",
				"insert_after": "rcm_submission_cb",
				"read_only": 1,
			},
			{
				"fieldname": "resubmission_type",
				"label": "Resubmission Type",
				"fieldtype": "Select",
				"options": "\nCorrection\nReconsideration\nAppeal",
				"insert_after": "resubmission_of",
				"depends_on": "resubmission_of",
			},
			{
				"fieldname": "payer_message",
				"label": "Payer Message / Information Request",
				"fieldtype": "Small Text",
				"insert_after": "resubmission_type",
				"read_only": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "validation_report",
				"label": "Pre-submission Validation",
				"fieldtype": "Small Text",
				"insert_after": "payer_message",
				"read_only": 1,
				"allow_on_submit": 1,
			},
		],
		"Insurance Claim Coverage": [
			{
				"fieldname": "rcm_line_section",
				"label": "Payer Adjudication",
				"fieldtype": "Section Break",
				"insert_after": "paid_amount",
			},
			{
				"fieldname": "external_claim_id",
				"label": "External Claim ID",
				"fieldtype": "Data",
				"insert_after": "rcm_line_section",
				"read_only": 1,
				"allow_on_submit": 1,
				"search_index": 1,
			},
			{
				"fieldname": "payer_adjudicated",
				"label": "Adjudicated by Payer",
				"fieldtype": "Check",
				"insert_after": "external_claim_id",
				"read_only": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "payer_approved_amount",
				"label": "Payer Approved Amount",
				"fieldtype": "Currency",
				"insert_after": "payer_adjudicated",
				"read_only": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "denial_code",
				"label": "Denial Code",
				"fieldtype": "Link",
				"options": "Denial Code",
				"insert_after": "payer_approved_amount",
				"allow_on_submit": 1,
			},
			{"fieldname": "rcm_line_cb", "fieldtype": "Column Break", "insert_after": "denial_code"},
			{
				"fieldname": "prior_authorization",
				"label": "Prior Authorization",
				"fieldtype": "Link",
				"options": "Prior Authorization Request",
				"insert_after": "rcm_line_cb",
				"read_only": 1,
			},
			{
				"fieldname": "practitioner",
				"label": "Practitioner",
				"fieldtype": "Link",
				"options": "Healthcare Practitioner",
				"insert_after": "prior_authorization",
				"read_only": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "diagnosis_codes",
				"label": "Diagnosis Codes",
				"fieldtype": "Data",
				"insert_after": "practitioner",
				"read_only": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "written_off_amount",
				"label": "Written Off",
				"fieldtype": "Currency",
				"insert_after": "diagnosis_codes",
				"read_only": 1,
				"allow_on_submit": 1,
			},
			{
				"fieldname": "rebilled_amount",
				"label": "Re-billed to Patient",
				"fieldtype": "Currency",
				"insert_after": "written_off_amount",
				"read_only": 1,
				"allow_on_submit": 1,
			},
		],
	}


# Marley 16.6.x: these fields fetch `code_value.description`, a column Code Value does not have;
# any coverage with a medical code then fails link validation. Point them at `display`.
FETCH_FIXES = [
	("Patient Insurance Coverage", "code_description", "code_value.display"),
	("Insurance Claim Coverage", "medical_code_description", "code_value.display"),
]


def fix_upstream_fetches():
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for doctype, fieldname, fetch_from in FETCH_FIXES:
		df = frappe.get_meta(doctype).get_field(fieldname)
		if df and df.fetch_from and df.fetch_from.endswith(".description"):
			make_property_setter(
				doctype, fieldname, "fetch_from", fetch_from, "Small Text", validate_fields_for_doctype=False
			)


def make_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def make_denial_codes():
	for code, description, category, patient_responsible, resubmittable in DEFAULT_DENIAL_CODES:
		if frappe.db.exists("Denial Code", code):
			continue
		frappe.get_doc(
			{
				"doctype": "Denial Code",
				"code": code,
				"description": description,
				"category": category,
				"patient_responsible": patient_responsible,
				"resubmittable": resubmittable,
				"source": "Internal",
			}
		).insert(ignore_permissions=True)


def before_install():
	make_roles()


def after_install():
	make_roles()
	apply_custom_fields(get_custom_fields())
	fix_upstream_fetches()
	make_denial_codes()
	frappe.db.commit()


def after_migrate():
	make_roles()
	apply_custom_fields(get_custom_fields())
	fix_upstream_fetches()
