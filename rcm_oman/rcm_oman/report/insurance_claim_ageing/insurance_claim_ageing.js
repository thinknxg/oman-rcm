// Copyright (c) 2026, Kreatao and contributors
frappe.query_reports["Insurance Claim Ageing"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "insurance_payor", label: __("Payer"), fieldtype: "Link", options: "Insurance Payor" },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "as_on", label: __("As On"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "include_closed", label: __("Include Closed"), fieldtype: "Check" },
	],
};
