frappe.ui.form.on("Billing Review", {
	refresh(frm) {
		if (!frappe.user.has_role("System Manager")) {
			return;
		}

		if (frm.doc.status === "Preview") {
			frm.set_intro(__(
				"Review the signed Contract and Subscription before creating drafts: included Care time, minimum time per case and additional services require a deliberate billing decision. Rates come from the submitted Timesheet in company currency; missing rates are excluded."
			), "blue");
			frm.add_custom_button(__("Create invoice drafts"), async () => {
				frappe.confirm(
					__(
						"Create draft Sales Invoices for all eligible rows? Nothing will be submitted or sent."
					),
					async () => {
						const result = await frappe.call({
							method: "working_time.platform_operations.create_billing_invoice_drafts",
							args: { review_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Creating draft invoices…"),
						});
						frappe.msgprint(
							__("Draft invoices: {0}", [
								(result.message.sales_invoices || []).join(", "),
							])
						);
						frm.reload_doc();
					}
				);
			});
		}

		if (frm.doc.status === "Draft Created") {
			frm.add_custom_button(__("Finalize submitted invoices"), () => {
				frappe.confirm(
					__(
						"Confirm that every linked Sales Invoice was reviewed and submitted? This action does not submit invoices."
					),
					async () => {
						await frappe.call({
							method: "working_time.platform_operations.finalize_billing_review",
							args: { review_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Finalizing billing review…"),
						});
						frm.reload_doc();
					}
				);
			});
		}
	},
});
