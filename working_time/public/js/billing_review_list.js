frappe.listview_settings["Billing Review"] = {
	onload(listview) {
		listview.page.add_inner_button(__("Create monthly review"), async () => {
			const today = frappe.datetime.get_today()
			const firstDay = frappe.datetime.month_start(today)
			const lastDay = frappe.datetime.month_end(today)
			const dialog = new frappe.ui.Dialog({
				title: __("Create billing review"),
				fields: [
					{ fieldname: "period_start", label: __("Period start"), fieldtype: "Date", default: firstDay, reqd: 1 },
					{ fieldname: "period_end", label: __("Period end"), fieldtype: "Date", default: lastDay, reqd: 1 },
				],
				primary_action_label: __("Create preview"),
				primary_action: async (values) => {
					const result = await frappe.call({
						method: "working_time.platform_operations.create_billing_review",
						args: values,
						freeze: true,
						freeze_message: __("Collecting billable time…"),
					})
					dialog.hide()
					frappe.set_route("Form", "Billing Review", result.message.name)
				},
			})
			dialog.show()
		})
	},
}
