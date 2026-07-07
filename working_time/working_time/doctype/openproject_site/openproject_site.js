frappe.ui.form.on("OpenProject Site", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Reconcile Time Entries"), async () => {
			const { message } = await frappe.call({
				method: "working_time.openproject_sync.reconcile_openproject_time_entries",
				freeze: true,
				freeze_message: __("Reconciling OpenProject time entries..."),
			});

			frappe.msgprint({
				title: __("OpenProject Reconciliation Finished"),
				message: __(
					"Created: {0}<br>Updated: {1}<br>Unchanged: {2}<br>Locked: {3}<br>Skipped: {4}",
					[
						message?.created || 0,
						message?.updated || 0,
						message?.unchanged || 0,
						message?.locked || 0,
						message?.skipped || 0,
					]
				),
				indicator: "green",
			});
		});
	},
});
