"""Transport plug-in point.

rcm_oman never imports a gateway. A transport app registers itself in its hooks.py:

    rcm_transport = "dhamani_gateway.api"

and that module must expose:

    is_enabled() -> bool
    is_available(facility_licence) -> bool          # breaker closed and credentials active
    check_eligibility(request: dict, context: dict) -> dict   # synchronous, canonical response
    send(message_type, payload: dict, reference_doctype, reference_name, context: dict) -> str
                                                     # queues an async message, returns its id

Inbound results come back through rcm_oman.events.*.
"""

import frappe


def get_transport():
	paths = frappe.get_hooks("rcm_transport") or []
	if not paths:
		return None
	try:
		module = frappe.get_module(paths[-1])
	except Exception:
		frappe.log_error(title="RCM: transport module could not be loaded")
		return None
	try:
		if not module.is_enabled():
			return None
	except Exception:
		return None
	return module


def build_context(company=None, branch=None, facility_licence=None):
	if not facility_licence and branch:
		from his_oman.licensing import get_facility_licence

		facility_licence = get_facility_licence(branch, company)
	return {"company": company, "branch": branch, "facility_licence": facility_licence}
