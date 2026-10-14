"""Eligibility: real-time check through the transport, manual verification, check-in gate."""

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, get_datetime, now_datetime, today

from rcm_oman.canonical import EligibilityRequest, to_dict
from rcm_oman.channel import MANUAL, resolve_channel
from rcm_oman.transport import get_transport
from rcm_oman.utils import int_setting, member_from_patient, party_for, setting

VERIFIED_STATES = ("Verified", "Unverified Override")


def _policy(insurance_policy):
	policy = frappe.get_doc("Patient Insurance Policy", insurance_policy)
	if policy.docstatus != 1:
		frappe.throw(_("Submit Patient Insurance Policy {0} before checking eligibility").format(policy.name))
	return policy


def _company_for(policy, company=None):
	return (
		company
		or frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)


def _branch_for(branch=None):
	if branch:
		return branch
	from his_oman.branch import get_user_branch

	return get_user_branch()


def _new_check(policy, company, branch, check_type, channel):
	check = frappe.get_doc(
		{
			"doctype": "Eligibility Check",
			"patient": policy.patient,
			"insurance_policy": policy.name,
			"company": company,
			"branch": branch,
			"check_type": check_type,
			"channel": channel,
			"status": "Pending",
			"checked_on": now_datetime(),
			"checked_by": frappe.session.user,
		}
	)
	check.insert(ignore_permissions=True)
	return check


@frappe.whitelist()
def check_eligibility(insurance_policy, check_type="Check-in", company=None, branch=None):
	frappe.has_permission("Patient Insurance Policy", "read", insurance_policy, throw=True)
	policy = _policy(insurance_policy)
	company = _company_for(policy, company)
	branch = _branch_for(branch)
	channel, context, reason = resolve_channel(policy.insurance_payor, company, branch, synchronous=True)
	check = _new_check(policy, company, branch, check_type, channel)

	if channel == MANUAL:
		check.db_set(
			{
				"status": "Unverified",
				"response_message": _("{0}. Verify with the payer and record the result.").format(reason),
			}
		)
		_update_policy(policy.name, check, verified=None)
		return check.as_dict()

	request = EligibilityRequest(
		reference=check.name,
		party=party_for(policy.insurance_payor, context.get("facility_licence")),
		member=member_from_patient(policy.patient, policy.name),
		service_date=today(),
		encounter_type="Inpatient" if check_type == "Admission" else "Outpatient",
	)
	try:
		response = get_transport().check_eligibility(to_dict(request), context)
	except Exception as e:
		frappe.log_error(title="RCM: eligibility check failed")
		check.db_set({"status": "Unverified", "channel": MANUAL, "response_message": str(e)[:500]})
		_update_policy(policy.name, check, verified=None)
		return check.as_dict()

	apply_eligibility_response(check.name, response)
	return frappe.get_doc("Eligibility Check", check.name).as_dict()


def apply_eligibility_response(check_name, response):
	"""Canonical EligibilityResponse dict -> Eligibility Check + policy status."""
	check = frappe.get_doc("Eligibility Check", check_name)
	if response.get("error"):
		check.db_set({"status": "Error", "response_message": str(response.get("error"))[:500]})
		_update_policy(check.insurance_policy, check, verified=None)
		return check

	eligible = bool(response.get("eligible"))
	hours = int_setting("eligibility_valid_hours", 24)
	check.db_set(
		{
			"status": "Eligible" if eligible else "Not Eligible",
			"member_id": response.get("member_id"),
			"plan_reference": response.get("plan_reference"),
			"payer_reference": response.get("payer_reference"),
			"copay_percent": flt(response.get("copay_percent")),
			"deductible": flt(response.get("deductible")),
			"annual_limit": flt(response.get("annual_limit")),
			"remaining_limit": flt(response.get("remaining_limit")),
			"response_message": (response.get("message") or "")[:500],
			"valid_until": add_to_date(now_datetime(), hours=hours) if eligible else None,
		}
	)
	_update_policy(check.insurance_policy, check, verified=eligible, member_id=response.get("member_id"))
	return check


def _update_policy(insurance_policy, check, verified, member_id=None):
	values = {"last_eligibility_check": check.name}
	if verified is True:
		values.update({"verification_status": "Verified", "last_verified_on": now_datetime()})
	elif verified is False:
		values.update({"verification_status": "Not Eligible", "last_verified_on": now_datetime()})
	if member_id:
		values["dhamani_member_id"] = member_id
	frappe.db.set_value("Patient Insurance Policy", insurance_policy, values)


@frappe.whitelist()
def record_manual_eligibility(
	insurance_policy, eligible, payer_reference, notes=None, company=None, branch=None
):
	"""Front desk confirmed with the payer by portal or phone; the payer reference is mandatory."""
	frappe.has_permission("Patient Insurance Policy", "read", insurance_policy, throw=True)
	if not payer_reference:
		frappe.throw(_("Payer reference is required for a manual verification"))
	policy = _policy(insurance_policy)
	eligible = frappe.parse_json(eligible) if isinstance(eligible, str) else eligible
	check = _new_check(policy, _company_for(policy, company), _branch_for(branch), "Manual Recheck", MANUAL)
	hours = int_setting("eligibility_valid_hours", 24)
	check.db_set(
		{
			"status": "Eligible" if eligible else "Not Eligible",
			"payer_reference": payer_reference,
			"response_message": notes,
			"valid_until": add_to_date(now_datetime(), hours=hours) if eligible else None,
		}
	)
	_update_policy(policy.name, check, verified=bool(eligible))
	return check.as_dict()


@frappe.whitelist()
def override_unverified(insurance_policy, reason):
	role = setting("unverified_override_role", "RCM Manager")
	if role not in frappe.get_roles():
		frappe.throw(
			_("Only users with role {0} can override eligibility").format(role), frappe.PermissionError
		)
	if not reason:
		frappe.throw(_("A reason is required"))
	frappe.db.set_value(
		"Patient Insurance Policy",
		insurance_policy,
		{"verification_status": "Unverified Override", "last_verified_on": now_datetime()},
	)
	frappe.get_doc("Patient Insurance Policy", insurance_policy).add_comment(
		"Comment", _("Eligibility overridden: {0}").format(reason)
	)
	return "Unverified Override"


def is_policy_verified(insurance_policy):
	status, verified_on = frappe.db.get_value(
		"Patient Insurance Policy", insurance_policy, ["verification_status", "last_verified_on"]
	) or (None, None)
	if status not in VERIFIED_STATES or not verified_on:
		return False
	hours = int_setting("eligibility_valid_hours", 24)
	return get_datetime(verified_on) >= add_to_date(now_datetime(), hours=-hours)


def validate_checkin(doc, method=None):
	"""Block check-in of an insured appointment until eligibility is verified or overridden."""
	if not doc.get("insurance_policy") or doc.status != "Checked In":
		return
	if not doc.is_new() and not doc.has_value_changed("status"):
		return
	if not int(setting("require_eligibility_before_checkin", 1) or 0):
		return
	if not is_policy_verified(doc.insurance_policy):
		frappe.throw(
			_(
				"Insurance policy {0} is not verified. Run an eligibility check, record a manual verification, or ask an RCM Manager to override."
			).format(frappe.bold(doc.insurance_policy)),
			title=_("Eligibility Required"),
		)


def on_policy_submit(doc, method=None):
	"""Check eligibility in the background when a policy is registered."""
	company = _company_for(doc)
	from rcm_oman.channel import get_contract_channel

	if company and get_contract_channel(doc.insurance_payor, company) != MANUAL:
		frappe.enqueue(
			"rcm_oman.eligibility.check_eligibility",
			insurance_policy=doc.name,
			check_type="Registration",
			company=company,
			enqueue_after_commit=True,
			queue="short",
		)
