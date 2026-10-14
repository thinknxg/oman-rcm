// RCM Oman: authorisation status on coverage
frappe.ui.form.on("Patient Insurance Coverage", {
	refresh(frm) {
		if (frm.doc.prior_authorization) {
			frm.add_custom_button(__("Prior Authorization"), () =>
				frappe.set_route("Form", "Prior Authorization Request", frm.doc.prior_authorization)
			);
		} else if (frm.doc.docstatus === 0 && frm.doc.mode_of_approval === "Manual" && !frm.is_new()) {
			frm.add_custom_button(__("Request Prior Authorization"), () =>
				frappe
					.call("rcm_oman.api.make_prior_authorization", { coverages: [frm.doc.name] })
					.then((r) => frappe.set_route("Form", "Prior Authorization Request", r.message))
			);
		}
	},
});
