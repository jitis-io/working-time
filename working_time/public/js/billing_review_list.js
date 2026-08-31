frappe.listview_settings["Billing Review"] = {
	onload(listview) {
		if (!frappe.user.has_role("System Manager")) return;
		listview.page.add_inner_button(__("Prepare month"), () => {
			const today = frappe.datetime.get_today();
			const dialog = new frappe.ui.Dialog({
				title: __("Create billing review"),
				fields: [
					{
						fieldname: "period_start",
						label: __("Period start"),
						fieldtype: "Date",
						default: frappe.datetime.month_start(today),
						reqd: 1,
					},
					{
						fieldname: "period_end",
						label: __("Period end"),
						fieldtype: "Date",
						default: frappe.datetime.month_end(today),
						reqd: 1,
					},
				],
				primary_action_label: __("Create preview"),
				primary_action: async (values) => {
					const result = await frappe.call({
						method: "working_time.platform_operations.create_billing_review",
						// Omitting a Project filter prepares every eligible customer Project.
						args: values,
						freeze: true,
						freeze_message: __("Collecting billable time…"),
					});
					const review = result.message?.name;
					if (!review) throw new Error(__("No billing review was created."));
					dialog.hide();
					frappe.set_route("Form", "Billing Review", review);
				},
			});
			dialog.show();
		});
	},
};
