// Copyright (c) 2026, Kreatao and contributors
frappe.ui.form.on("Denial Case", {
	refresh(frm) {
		if (frm.is_new() || ["Written Off", "Rebilled to Patient", "Recovered", "Closed"].includes(frm.doc.status)) return;
		const amount_prompt = (label, method) =>
			frappe.prompt(
				[
					{ fieldname: "amount", fieldtype: "Currency", label: __("Amount"), default: flt(frm.doc.denied_amount) - flt(frm.doc.recovered_amount) - flt(frm.doc.written_off_amount) - flt(frm.doc.rebilled_amount) },
					{ fieldname: "remark", fieldtype: "Small Text", label: __("Remark") },
				],
				(v) => frm.call(method, v).then(() => frm.reload_doc()),
				label
			);
		frm.add_custom_button(__("Resubmit"), () => frm.call("resubmit").then((r) => frappe.set_route("Form", "Insurance Claim", r.message)), __("Action"));
		frm.add_custom_button(__("Write Off"), () => amount_prompt(__("Write Off"), "write_off"), __("Action"));
		frm.add_custom_button(__("Re-bill Patient"), () => amount_prompt(__("Re-bill Patient"), "rebill_patient"), __("Action"));
	},
});
