frappe.ui.form.on("Billing Review", {
	refresh(frm) {
		if (frm.doc.status !== "Preview" || !frappe.user.has_role("System Manager")) {
			return
		}

		frm.add_custom_button(__("Create invoice drafts"), async () => {
			frappe.confirm(
				__("Create draft Sales Invoices for all eligible rows? Nothing will be submitted or sent."),
				async () => {
					const result = await frappe.call({
						method: "working_time.platform_operations.create_billing_invoice_drafts",
						args: { review_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Creating draft invoices…"),
					})
					frappe.msgprint(__("Draft invoices: {0}", [(result.message.sales_invoices || []).join(", ")]))
					frm.reload_doc()
				},
			)
		})
	},
})
