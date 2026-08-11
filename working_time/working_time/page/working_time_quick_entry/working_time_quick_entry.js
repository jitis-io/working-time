frappe.pages["working-time-quick-entry"].on_page_load = async function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Zeit buchen"), single_column: true });
	const issue = frappe.utils.get_url_arg("issue");
	if (!issue) {
		page.main.html(`<div class="frappe-card p-4">${__("No issue selected.")}</div>`);
		return;
	}
	const context = await frappe.xcall("working_time.issues.get_issue_time_context", {
		issue,
		date: frappe.datetime.get_today(),
	});
	const fields = new frappe.ui.FieldGroup({
		body: page.main,
		fields: [
			{ fieldname: "issue", fieldtype: "Link", options: "Issue", label: __("Issue"), read_only: 1, default: context.issue },
			{ fieldname: "date", fieldtype: "Date", label: __("Date"), reqd: 1, default: context.date },
			{ fieldname: "start_time", fieldtype: "Time", label: __("Start time"), reqd: 1, default: frappe.datetime.now_time() },
			{ fieldname: "duration_minutes", fieldtype: "Int", label: __("Duration (minutes)"), reqd: 1 },
			{ fieldname: "customer_description", fieldtype: "Small Text", label: __("Customer Description") },
			{ fieldname: "internal_note", fieldtype: "Small Text", label: __("Internal Note") },
			{ fieldname: "billable", fieldtype: "Check", label: __("Billable"), default: 1 },
		],
	});
	fields.make();
	page.set_primary_action(__("Book time"), async () => {
		const values = fields.get_values();
		if (!values) return;
		const result = await frappe.xcall("working_time.issues.add_issue_time", {
			issue,
			project: context.project || null,
			task: context.task || null,
			...values,
		});
		frappe.show_alert({ message: __("Time booked"), indicator: "green" });
		window.location.href = result.route;
	});
};
