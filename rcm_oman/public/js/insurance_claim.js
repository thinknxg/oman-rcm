// RCM Oman: claim submission actions
frappe.ui.form.on("Insurance Claim", {
	refresh(frm) {
		const status = frm.doc.submission_status;
		if (status) {
			const color =
				{ Paid: "green", Adjudicated: "blue", Accepted: "blue", Sent: "blue", Queued: "orange", "Partly Paid": "orange", "Information Requested": "orange", "Rejected by Platform": "red", "Manual Pack Generated": "grey" }[status] || "grey";
			frm.dashboard.add_indicator(__("{0} · {1}", [__(frm.doc.rcm_channel || ""), __(status)]), color);
		}
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.add_custom_button(__("Validate"), () =>
				frm.call("run_validation").then((r) => {
					frappe.msgprint({ title: __("Pre-submission Validation"), message: `<pre style="white-space:pre-wrap">${frappe.utils.escape_html(r.message.report)}</pre>` });
				})
			);
		}
		if (frm.doc.docstatus !== 1) return;

		frm.add_custom_button(__("Download Claim Pack"), () =>
			frappe.call("rcm_oman.claims.pack.generate_manual_pack", { claim_name: frm.doc.name }).then((r) => {
				window.open(r.message);
				frm.reload_doc();
			}), __("Payer")
		);
		if (["Rejected by Platform", "Manual Pack Generated", "Not Sent"].includes(status)) {
			frm.add_custom_button(__("Send via Dhamani"), () => frm.call("resend").then(() => frm.reload_doc()), __("Payer"));
		}
		if (["Queued", "Rejected by Platform"].includes(status)) {
			frm.add_custom_button(__("Switch to Manual"), () => frm.call("switch_to_manual").then(() => frm.reload_doc()), __("Payer"));
		}
		if (status === "Information Requested") {
			frm.add_custom_button(
				__("Reply to Payer"),
				() => {
					const d = new frappe.ui.Dialog({
						title: __("Reply to Information Request"),
						fields: [
							{ fieldname: "request", fieldtype: "Small Text", label: __("Payer asked"), read_only: 1, default: frm.doc.payer_message },
							{ fieldname: "message", fieldtype: "Small Text", label: __("Reply"), reqd: 1 },
							{ fieldname: "attachment", fieldtype: "Attach", label: __("Attachment") },
						],
						primary_action_label: __("Send"),
						primary_action(v) {
							frm.call("reply_information", { message: v.message, attachments: v.attachment ? [v.attachment] : [] }).then(() => {
								d.hide();
								frm.reload_doc();
							});
						},
					});
					d.show();
				},
				__("Payer")
			);
		}
		const hasDenials = (frm.doc.coverages || []).some(
			(r) => r.status === "Rejected" || (r.payer_adjudicated && flt(r.payer_approved_amount) < flt(r.claim_amount))
		);
		if (hasDenials) {
			frm.add_custom_button(
				__("Resubmit Denied Lines"),
				() =>
					frappe.prompt(
						{ fieldname: "resubmission_type", fieldtype: "Select", options: "Correction\nReconsideration\nAppeal", default: "Correction", label: __("Type") },
						(v) => frm.call("make_resubmission", v).then((r) => frappe.set_route("Form", "Insurance Claim", r.message)),
						__("Resubmission")
					),
				__("Payer")
			);
			frm.add_custom_button(__("Denial Cases"), () => frappe.set_route("List", "Denial Case", { insurance_claim: frm.doc.name }), __("Payer"));
		}
	},
});
