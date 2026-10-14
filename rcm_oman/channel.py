"""Which channel a transaction takes: Dhamani (direct) or Manual (fallback).

Order of decision:
1. The payer's active Insurance Payor Contract channel (Manual / Dhamani / Hybrid).
2. Whether a transport is installed and enabled.
3. For synchronous calls (eligibility) and Hybrid contracts: whether the gateway is available
   for the branch's facility licence (circuit breaker closed, credentials active).

Dhamani contracts keep async messages on the Dhamani channel even while the breaker is open:
they wait in the outbox and replay when the link recovers. Hybrid contracts fall back to the
manual channel immediately.
"""

import frappe
from frappe.utils import getdate, today

from rcm_oman.transport import build_context, get_transport

MANUAL = "Manual"
DHAMANI = "Dhamani"


def get_contract_channel(insurance_payor, company, on_date=None):
	on_date = getdate(on_date or today())
	contracts = frappe.get_all(
		"Insurance Payor Contract",
		filters={"insurance_payor": insurance_payor, "company": company, "docstatus": 1, "is_active": 1},
		fields=["name", "start_date", "end_date", "rcm_channel"],
		order_by="start_date desc",
	)
	for c in contracts:
		if c.start_date and getdate(c.start_date) > on_date:
			continue
		if c.end_date and getdate(c.end_date) < on_date:
			continue
		return c.rcm_channel or MANUAL
	return MANUAL


def resolve_channel(insurance_payor, company, branch=None, on_date=None, synchronous=False):
	"""Returns (channel, context, reason)."""
	contract_channel = get_contract_channel(insurance_payor, company, on_date)
	context = build_context(company=company, branch=branch)
	if contract_channel == MANUAL:
		return MANUAL, context, "Payer contract is manual"

	transport = get_transport()
	if not transport:
		return MANUAL, context, "Dhamani gateway not installed or disabled"

	if not context.get("facility_licence"):
		return MANUAL, context, "No active Facility Licence for branch"

	if synchronous or contract_channel == "Hybrid":
		if not transport.is_available(context["facility_licence"]):
			return MANUAL, context, "Dhamani link unavailable (circuit breaker open)"

	return DHAMANI, context, None


def get_payer_code(insurance_payor):
	return frappe.db.get_value("Insurance Payor", insurance_payor, "dhamani_payer_code")
