frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role("System Manager")) {
			return
		}

		frm.add_custom_button(__("Prepare offboarding"), async () => {
			const preview = await frappe.call({
				method: "working_time.platform_operations.prepare_customer_offboarding",
				args: { customer: frm.doc.name },
				freeze: true,
				freeze_message: __("Preparing offboarding…"),
			})
			const result = preview.message
			frappe.confirm(
				__(
					"Remove portal access through the customer Keycloak group? Accounts and data will remain.\n\n{0}",
					[JSON.stringify(result.preview || {}, null, 2)],
				),
				async () => {
					await frappe.call({
						method: "working_time.platform_operations.confirm_customer_offboarding",
						args: { offboarding_name: result.name },
					})
					frappe.set_route("Form", "Customer Offboarding", result.name)
				},
			)
		})
	},
})
