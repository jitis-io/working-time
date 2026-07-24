frappe.ui.form.on("OpenProject Site", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(
			__("Queue Time Entry Reconciliation"),
			async () => {
				const { message } = await frappe.call({
					method: "working_time.platform_operations.queue_incremental_time_entry_reconciliation",
					freeze: true,
					freeze_message: __(
						"Queueing OpenProject reconciliation..."
					),
				});

				frappe.msgprint({
					title: __("OpenProject Reconciliation Queued"),
					message: __("Run {0} is now queued.", [message]),
					indicator: "green",
				});
			}
		);

		frm.add_custom_button(__("Integration Control Center"), () => {
			frappe.set_route("workspace", "Integration Control Center");
		});
	},
});
