app_name = "rcm_oman"
app_title = "RCM Oman"
app_publisher = "Kreatao"
app_description = "Revenue cycle for Marley Health in Oman: eligibility, prior authorisation, copay, claims, remittance, denials"
app_email = "kreataothinkcadd@gmail.com"
app_license = "GPL-3.0"

required_apps = ["frappe", "erpnext", "healthcare", "his_oman"]

before_install = "rcm_oman.install.before_install"
after_install = "rcm_oman.install.after_install"
after_migrate = "rcm_oman.install.after_migrate"

override_doctype_class = {
	"Insurance Claim": "rcm_oman.overrides.insurance_claim.RCMInsuranceClaim",
}

doctype_js = {
	"Insurance Claim": "public/js/insurance_claim.js",
	"Patient Insurance Policy": ["public/js/eligibility.js", "public/js/patient_insurance_policy.js"],
	"Patient Appointment": ["public/js/eligibility.js", "public/js/patient_appointment.js"],
	"Patient Insurance Coverage": "public/js/patient_insurance_coverage.js",
}

doc_events = {
	"Patient Insurance Coverage": {
		"validate": "rcm_oman.coverage.apply_patient_share",
		"on_update": "rcm_oman.prior_auth.ensure_prior_authorization",
	},
	"Patient Insurance Policy": {
		"on_submit": "rcm_oman.eligibility.on_policy_submit",
	},
	"Patient Appointment": {
		"validate": "rcm_oman.eligibility.validate_checkin",
	},
}

scheduler_events = {
	"daily": [
		"rcm_oman.prior_auth.expire_authorizations",
		"rcm_oman.denials.remind_overdue_cases",
	],
}
