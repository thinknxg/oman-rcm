// RCM Oman: shared eligibility buttons (policy and appointment forms)
frappe.provide("rcm_oman");

rcm_oman.eligibility_buttons = function (frm, policy) {
	frm.add_custom_button(
		__("Check Eligibility"),
		() =>
			frappe
				.call({
					method: "rcm_oman.eligibility.check_eligibility",
					args: { insurance_policy: policy, check_type: "Check-in" },
					freeze: true,
					freeze_message: __("Checking eligibility..."),
				})
				.then((r) => {
					const c = r.message || {};
					const indicator = { Eligible: "green", "Not Eligible": "red" }[c.status] || "orange";
					frappe.msgprint({
						title: __("Eligibility: {0}", [__(c.status)]),
						indicator,
						message: [c.channel && __("Channel: {0}", [c.channel]), c.member_id && __("Member ID: {0}", [c.member_id]), c.response_message]
							.filter(Boolean)
							.join("<br>"),
					});
					frm.reload_doc();
				}),
		__("Eligibility")
	);
	frm.add_custom_button(
		__("Record Manual Verification"),
		() => {
			const d = new frappe.ui.Dialog({
				title: __("Manual Verification"),
				fields: [
					{ fieldname: "eligible", fieldtype: "Select", label: __("Result"), options: "Eligible\nNot Eligible", reqd: 1 },
					{ fieldname: "payer_reference", fieldtype: "Data", label: __("Payer Reference"), reqd: 1 },
					{ fieldname: "notes", fieldtype: "Small Text", label: __("Notes") },
				],
				primary_action_label: __("Save"),
				primary_action(values) {
					frappe
						.call("rcm_oman.eligibility.record_manual_eligibility", {
							insurance_policy: policy,
							eligible: values.eligible === "Eligible" ? 1 : 0,
							payer_reference: values.payer_reference,
							notes: values.notes,
						})
						.then(() => {
							d.hide();
							frm.reload_doc();
						});
				},
			});
			d.show();
		},
		__("Eligibility")
	);
	frm.add_custom_button(
		__("Override (RCM Manager)"),
		() =>
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				(v) =>
					frappe
						.call("rcm_oman.eligibility.override_unverified", { insurance_policy: policy, reason: v.reason })
						.then(() => frm.reload_doc()),
				__("Override Eligibility")
			),
		__("Eligibility")
	);
};

