frappe.ui.form.on("Customer Project Provisioning", {
	refresh(frm) {
		if (frm.doc.status !== "Failed" || !frappe.user.has_role("System Manager")) {
			return
		}

		frm.add_custom_button(__("Retry provisioning"), async () => {
			await frappe.call({
				method: "working_time.platform_operations.confirm_customer_project_provisioning",
				args: { provisioning_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Queueing provisioning retry…"),
			})
			frm.reload_doc()
		})
	},
})
