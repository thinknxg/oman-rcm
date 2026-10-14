# Copyright (c) 2026, Kreatao and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, today

BUCKETS = [(0, 30, "0-30"), (31, 45, "31-45"), (46, 60, "46-60"), (61, 90, "61-90"), (91, 10**6, "90+")]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters), None, get_chart(filters)


def get_columns():
	return [
		{
			"label": _("Insurance Claim"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Insurance Claim",
			"width": 160,
		},
		{
			"label": _("Payer"),
			"fieldname": "insurance_payor",
			"fieldtype": "Link",
			"options": "Insurance Payor",
			"width": 150,
		},
		{"label": _("Branch"), "fieldname": "branch", "fieldtype": "Link", "options": "Branch", "width": 120},
		{"label": _("Channel"), "fieldname": "rcm_channel", "fieldtype": "Data", "width": 90},
		{"label": _("Submission"), "fieldname": "submission_status", "fieldtype": "Data", "width": 140},
		{"label": _("Submitted On"), "fieldname": "submitted_date", "fieldtype": "Date", "width": 100},
		{"label": _("Age (Days)"), "fieldname": "age", "fieldtype": "Int", "width": 80},
		{"label": _("Bucket"), "fieldname": "bucket", "fieldtype": "Data", "width": 70},
		{"label": _("Claimed"), "fieldname": "insurance_claim_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Approved"), "fieldname": "approved_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Rejected"), "fieldname": "rejected_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Paid"), "fieldname": "paid_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Awaiting Payer"), "fieldname": "awaiting", "fieldtype": "Currency", "width": 120},
		{"label": _("Over 45-day SLA"), "fieldname": "over_sla", "fieldtype": "Check", "width": 90},
	]


def bucket_of(age):
	for lo, hi, label in BUCKETS:
		if lo <= age <= hi:
			return label
	return BUCKETS[-1][2]


def get_data(filters):
	conditions = {"docstatus": 1}
	if filters.company:
		conditions["company"] = filters.company
	if filters.insurance_payor:
		conditions["insurance_payor"] = filters.insurance_payor
	if filters.branch:
		conditions["branch"] = filters.branch
	if not filters.include_closed:
		conditions["status"] = ("not in", ["Completed", "Error", "Cancelled"])
	claims = frappe.get_all(
		"Insurance Claim",
		filters=conditions,
		fields=[
			"name",
			"insurance_payor",
			"branch",
			"rcm_channel",
			"submission_status",
			"submitted_on",
			"posting_date",
			"insurance_claim_amount",
			"approved_amount",
			"rejected_amount",
			"paid_amount",
			"status",
		],
		order_by="posting_date asc",
	)
	as_on = getdate(filters.as_on or today())
	data = []
	for c in claims:
		start = getdate(c.submitted_on) if c.submitted_on else getdate(c.posting_date)
		c.submitted_date = start
		c.age = max(date_diff(as_on, start), 0)
		c.bucket = bucket_of(c.age)
		decided = flt(c.approved_amount) + flt(c.rejected_amount)
		c.awaiting = flt(c.insurance_claim_amount) - flt(c.rejected_amount) - flt(c.paid_amount)
		c.over_sla = 1 if c.age > 45 and decided < flt(c.insurance_claim_amount) else 0
		data.append(c)
	return data


def get_chart(filters):
	data = get_data(filters)
	totals = {label: 0 for _lo, _hi, label in BUCKETS}
	for row in data:
		totals[row.bucket] += flt(row.awaiting)
	return {
		"data": {
			"labels": list(totals),
			"datasets": [{"name": _("Awaiting Payer"), "values": list(totals.values())}],
		},
		"type": "bar",
	}
