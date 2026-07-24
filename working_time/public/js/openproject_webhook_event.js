frappe.ui.form.on("OpenProject Webhook Event", {
	refresh(frm) {
		if (frm.doc.status !== "Failed" || !frappe.user.has_role("System Manager")) {
			return
		}

		frm.add_custom_button(__("Retry"), async () => {
			await frappe.call({
				method: "working_time.platform_operations.retry_openproject_webhook_event",
				args: { event_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Queueing retry…"),
			})
			frm.reload_doc()
		})
	},
})
