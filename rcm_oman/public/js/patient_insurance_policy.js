// RCM Oman: eligibility on the policy (helpers in eligibility.js)
frappe.ui.form.on("Patient Insurance Policy", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) rcm_oman.eligibility_buttons(frm, frm.doc.name);
		if (frm.doc.verification_status) {
			const color = { Verified: "green", "Unverified Override": "orange", "Not Eligible": "red" }[frm.doc.verification_status] || "grey";
			frm.dashboard.add_indicator(__("Eligibility: {0}", [__(frm.doc.verification_status)]), color);
		}
	},
});
