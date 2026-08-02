frappe.pages["working-time-quick-entry"].on_page_load = async function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Zeit buchen"), single_column: true });
	const ticket = frappe.utils.get_url_arg("ticket");
	if (!ticket) {
		page.main.html(`<div class="frappe-card p-4">${__("No ticket selected.")}</div>`);
		return;
	}
	const context = await frappe.xcall("working_time.helpdesk.get_ticket_time_context", {
		ticket,
		date: frappe.datetime.get_today(),
	});
	const fields = new frappe.ui.FieldGroup({
		body: page.main,
		fields: [
			{ fieldname: "ticket", fieldtype: "Link", options: "HD Ticket", label: __("Ticket"), read_only: 1, default: context.ticket },
			{ fieldname: "date", fieldtype: "Date", label: __("Date"), reqd: 1, default: context.date },
			{ fieldname: "duration_minutes", fieldtype: "Int", label: __("Duration (minutes)"), reqd: 1 },
			{ fieldname: "project", fieldtype: "Link", options: "Project", label: __("Project"), reqd: 1, default: context.project, get_query: () => ({ filters: { name: ["in", context.projects.map((row) => row.name)] } }) },
			{ fieldname: "task", fieldtype: "Link", options: "Task", label: __("Task"), default: context.task, get_query: () => ({ filters: { project: fields.get_value("project") } }) },
			{ fieldname: "customer_description", fieldtype: "Small Text", label: __("Customer Description") },
			{ fieldname: "internal_note", fieldtype: "Small Text", label: __("Internal Note") },
			{ fieldname: "billable", fieldtype: "Check", label: __("Billable"), default: 1 },
		],
	});
	fields.make();
	page.set_primary_action(__("Book time"), async () => {
		const values = fields.get_values();
		if (!values) return;
		const result = await frappe.xcall("working_time.helpdesk.add_ticket_time", { ticket, ...values });
		frappe.show_alert({ message: __("Time booked"), indicator: "green" });
		window.location.href = result.route;
	});
};
