frappe.pages["working-time-quick-entry"].on_page_load = async function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Book time"),
		single_column: true,
	});
	const task = frappe.utils.get_url_arg("task");
	const issue = frappe.utils.get_url_arg("issue");
	const workItemType = task ? "Task" : "Issue";
	const workItem = task || issue;
	if (!workItem) {
		page.main.html(`<div class="frappe-card p-4">${__("No work item selected.")}</div>`);
		return;
	}

	let context;
	try {
		context = await frappe.xcall(
			task
				? "working_time.issues.get_task_time_context"
				: "working_time.issues.get_issue_time_context",
			{
				[task ? "task" : "issue"]: workItem,
				date: frappe.datetime.get_today(),
			}
		);
	} catch (error) {
		page.main.empty().append($("<div class='frappe-card p-4 text-danger'></div>").text(error.message));
		return;
	}

	const fields = new frappe.ui.FieldGroup({
		body: page.main,
		fields: [
			{
				fieldname: "work_item",
				fieldtype: "Link",
				options: workItemType,
				label: __(workItemType),
				read_only: 1,
				default: workItem,
			},
			{
				fieldname: "project",
				fieldtype: "Link",
				options: "Project",
				label: __("Project"),
				read_only: 1,
				default: context.project,
			},
			{
				fieldname: "date",
				fieldtype: "Date",
				label: __("Date"),
				reqd: 1,
				default: context.date,
			},
			{
				fieldname: "start_time",
				fieldtype: "Time",
				label: __("Start time"),
				reqd: 1,
				default: frappe.datetime.now_time(),
			},
			{
				fieldname: "duration_minutes",
				fieldtype: "Int",
				label: __("Duration (minutes)"),
				reqd: 1,
			},
			{
				fieldname: "customer_description",
				fieldtype: "Small Text",
				label: __("Customer Description"),
			},
			{
				fieldname: "internal_note",
				fieldtype: "Small Text",
				label: __("Internal Note"),
			},
			{
				fieldname: "billable",
				fieldtype: "Check",
				label: __("Billable"),
				default: context.billable ? 1 : 0,
			},
		],
	});
	fields.make();
	if (context.project_ambiguous) {
		$(
			`<div class="alert alert-warning mt-3">${__(
				"This ticket has more than one possible customer project. Booked time remains in the daily draft until you select the correct project."
			)}</div>`
		).prependTo(page.main);
	}
	page.set_primary_action(__("Book time"), async () => {
		const values = fields.get_values();
		if (!values) return;
		delete values.work_item;
		delete values.project;
		const result = await frappe.xcall(
			task ? "working_time.issues.add_task_time" : "working_time.issues.add_issue_time",
			{ [task ? "task" : "issue"]: workItem, ...values }
		);
		frappe.show_alert({ message: __("Time booked"), indicator: "green" });
		window.location.href = result.route;
	});
};
