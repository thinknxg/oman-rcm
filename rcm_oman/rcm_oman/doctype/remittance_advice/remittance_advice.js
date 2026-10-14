// Copyright (c) 2026, Kreatao and contributors
frappe.ui.form.on("Remittance Advice", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.import_file) {
			frm.add_custom_button(__("Import Lines"), () =>
				frm.call("import_lines").then((r) => {
					frappe.show_alert({ message: __("{0} lines imported", [r.message]), indicator: "green" });
					frm.reload_doc();
				})
			);
		}
		if (frm.doc.docstatus === 1 && frm.doc.payment_entries) {
			frm.add_custom_button(__("Payment Entries"), () =>
				frappe.set_route("List", "Payment Entry", { name: ["in", frm.doc.payment_entries.split("\n")] })
			);
		}
	},
	insurance_payor(frm) {
		frm.set_query("insurance_claim", "items", () => ({ filters: { insurance_payor: frm.doc.insurance_payor, docstatus: 1 } }));
	},
	setup(frm) {
		frm.set_query("paid_to", () => ({ filters: { company: frm.doc.company, account_type: ["in", ["Bank", "Cash"]], is_group: 0 } }));
	},
});
