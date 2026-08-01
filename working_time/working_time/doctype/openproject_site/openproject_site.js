frappe.ui.form.on("OpenProject Site", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frappe.user.has_role("System Manager")) {
			frm.add_custom_button(__("Queue one-time reconciliation"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("One-time OpenProject reconciliation"),
					fields: [
						{
							fieldname: "warning",
							fieldtype: "HTML",
							options: __(
								"<p class=\"text-muted\">Use this only for the controlled final import. Reconciliation is no longer scheduled automatically.</p>"
							),
						},
						{
							fieldname: "reconciliation_type",
							fieldtype: "Select",
							label: __("Type"),
							options: [
								"Time Entries",
								"Projects and Work Packages",
								"Time Entry Deletions",
							],
							default: "Time Entries",
							reqd: 1,
						},
					],
					primary_action_label: __("Queue once"),
					primary_action: async (values) => {
						const { message } = await frappe.call({
							method: "working_time.platform_operations.queue_reconciliation",
							args: {
								reconciliation_type: values.reconciliation_type,
								openproject_site: frm.doc.name,
							},
							freeze: true,
							freeze_message: __("Queueing one-time reconciliation..."),
						});
						dialog.hide();
						frappe.msgprint({
							title: __("OpenProject Reconciliation Queued"),
							message: __("Run {0} is now queued.", [message]),
							indicator: "green",
						});
					},
				});
				dialog.show();
			});
		}

		frm.add_custom_button(__("Integration Control Center"), () => {
			frappe.set_route("workspace", "Integration Control Center");
		});
	},
});
