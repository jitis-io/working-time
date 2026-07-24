frappe.ui.form.on("Platform Operations Settings", {
	refresh(frm) {
		if (
			!frm.doc.teams_webhook_url ||
			!frappe.user.has_role("System Manager")
		) {
			return;
		}

		frm.add_custom_button(__("Send Teams test alert"), async () => {
			const response = await frappe.call({
				method: "working_time.platform_operations.send_test_teams_alert",
				freeze: true,
				freeze_message: __("Sending Teams test alert…"),
			});
			frappe.show_alert({
				message: __("Teams webhook accepted the test card ({0})", [
					response.message.name,
				]),
				indicator: "green",
			});
		});
	},
});
