// Copyright (c) 2026, Kreatao and contributors
frappe.ui.form.on("Prior Authorization Request", {
	refresh(frm) {
		const color = { Approved: "green", "Partially Approved": "blue", Rejected: "red", Pending: "orange", "Information Requested": "orange", Error: "red" }[frm.doc.status];
		if (color) frm.page.set_indicator(__(frm.doc.status), color);
		if (frm.doc.docstatus !== 1) return;

		if (["Pending", "Information Requested", "Error"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Record Payer Decision"), () => record_decision(frm), __("Payer"));
		}
		if (frm.doc.channel === "Dhamani" && ["Pending", "Error"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Re-send via Dhamani"), () => frm.call("send").then(() => frm.reload_doc()), __("Payer"));
			frm.add_custom_button(__("Switch to Manual"), () => frm.call("switch_to_manual").then(() => frm.reload_doc()), __("Payer"));
		}
	},
});

function record_decision(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Payer Decision"),
		size: "large",
		fields: [
			{ fieldname: "status", fieldtype: "Select", label: __("Decision"), options: "Approved\nPartially Approved\nRejected", reqd: 1, default: "Approved" },
			{ fieldname: "approval_number", fieldtype: "Data", label: __("Approval Number"), depends_on: "eval:doc.status!='Rejected'" },
			{ fieldname: "col", fieldtype: "Column Break" },
			{ fieldname: "valid_till", fieldtype: "Date", label: __("Valid Till") },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Payer Message") },
			{ fieldname: "sec", fieldtype: "Section Break", label: __("Items") },
			{
				fieldname: "items",
				fieldtype: "Table",
				cannot_add_rows: true,
				in_place_edit: true,
				data: frm.doc.items.map((i) => ({ name: i.name, item_code: i.item_code, requested_amount: i.requested_amount, approved_amount: i.requested_amount, approved_qty: i.qty, status: "Approved" })),
				fields: [
					{ fieldname: "name", fieldtype: "Data", hidden: 1 },
					{ fieldname: "item_code", fieldtype: "Data", label: __("Item"), read_only: 1, in_list_view: 1 },
					{ fieldname: "requested_amount", fieldtype: "Currency", label: __("Requested"), read_only: 1, in_list_view: 1 },
					{ fieldname: "approved_amount", fieldtype: "Currency", label: __("Approved"), in_list_view: 1 },
					{ fieldname: "approved_qty", fieldtype: "Float", label: __("Qty"), in_list_view: 1 },
					{ fieldname: "status", fieldtype: "Select", options: "Approved\nPartially Approved\nRejected", label: __("Status"), in_list_view: 1 },
					{ fieldname: "reason_code", fieldtype: "Link", options: "Denial Code", label: __("Reason Code") },
				],
			},
		],
		primary_action_label: __("Apply"),
		primary_action(v) {
			frappe
				.call("rcm_oman.prior_auth.record_manual_decision", {
					name: frm.doc.name,
					status: v.status,
					approval_number: v.approval_number,
					valid_till: v.valid_till,
					reason: v.reason,
					items: v.items,
				})
				.then(() => {
					d.hide();
					frm.reload_doc();
				});
		},
	});
	d.show();
}
