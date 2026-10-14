# Copyright (c) 2026, Kreatao and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{
			"label": _("Payer"),
			"fieldname": "insurance_payor",
			"fieldtype": "Link",
			"options": "Insurance Payor",
			"width": 160,
		},
		{
			"label": _("Denial Code"),
			"fieldname": "denial_code",
			"fieldtype": "Link",
			"options": "Denial Code",
			"width": 110,
		},
		{"label": _("Description"), "fieldname": "description", "fieldtype": "Data", "width": 240},
		{"label": _("Category"), "fieldname": "category", "fieldtype": "Data", "width": 110},
		{"label": _("Cases"), "fieldname": "cases", "fieldtype": "Int", "width": 70},
		{"label": _("Denied"), "fieldname": "denied", "fieldtype": "Currency", "width": 110},
		{"label": _("Recovered"), "fieldname": "recovered", "fieldtype": "Currency", "width": 110},
		{"label": _("Written Off"), "fieldname": "written_off", "fieldtype": "Currency", "width": 110},
		{"label": _("Re-billed"), "fieldname": "rebilled", "fieldtype": "Currency", "width": 110},
		{"label": _("Open"), "fieldname": "open", "fieldtype": "Currency", "width": 110},
		{"label": _("Recovery %"), "fieldname": "recovery_pct", "fieldtype": "Percent", "width": 90},
	]
	conditions = {}
	for f in ("company", "insurance_payor", "branch"):
		if filters.get(f):
			conditions[f] = filters.get(f)
	if filters.from_date and filters.to_date:
		conditions["creation"] = ("between", [filters.from_date, filters.to_date])
	rows = frappe.get_all(
		"Denial Case",
		filters=conditions,
		fields=[
			"insurance_payor",
			"denial_code",
			"denied_amount",
			"recovered_amount",
			"written_off_amount",
			"rebilled_amount",
		],
	)
	grouped = {}
	for r in rows:
		key = (r.insurance_payor, r.denial_code)
		g = grouped.setdefault(
			key,
			frappe._dict(
				insurance_payor=r.insurance_payor,
				denial_code=r.denial_code,
				cases=0,
				denied=0,
				recovered=0,
				written_off=0,
				rebilled=0,
			),
		)
		g.cases += 1
		g.denied += flt(r.denied_amount)
		g.recovered += flt(r.recovered_amount)
		g.written_off += flt(r.written_off_amount)
		g.rebilled += flt(r.rebilled_amount)
	data = []
	for g in sorted(grouped.values(), key=lambda x: x.denied, reverse=True):
		if g.denial_code:
			g.description, g.category = frappe.db.get_value(
				"Denial Code", g.denial_code, ["description", "category"]
			) or ("", "")
		g.open = g.denied - g.recovered - g.written_off - g.rebilled
		g.recovery_pct = (g.recovered / g.denied * 100) if g.denied else 0
		data.append(g)
	return columns, data
