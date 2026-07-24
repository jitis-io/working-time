frappe.ui.form.on("Customer Offboarding", {
	refresh(frm) {
		if (frm.doc.status !== "Completed" || !frappe.user.has_role("System Manager")) {
			return
		}

		frm.add_custom_button(__("Reactivate portal access"), async () => {
			frappe.confirm(__("Restore the previously removed customer portal memberships?"), async () => {
				await frappe.call({
					method: "working_time.platform_operations.reactivate_customer_offboarding",
					args: { offboarding_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Restoring portal access…"),
				})
				frm.reload_doc()
			})
		})
	},
})
