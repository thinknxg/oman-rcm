// RCM Oman: eligibility from the appointment (check-in is blocked until verified)
frappe.ui.form.on("Patient Appointment", {
	refresh(frm) {
		if (!frm.doc.insurance_policy || frm.is_new()) return;
		rcm_oman.eligibility_buttons(frm, frm.doc.insurance_policy);
	},
});
