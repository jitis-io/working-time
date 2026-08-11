frappe.ui.form.on("Issue", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Zeit buchen"), () => {
			window.location.href = `/app/working-time-quick-entry?issue=${encodeURIComponent(frm.doc.name)}`;
		});
		if (!["Resolved", "Closed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("In Task übernehmen"), () => promote_issue(frm), __("Create"));
		}
	},
});

async function promote_issue(frm) {
	const context = await frappe.xcall("working_time.work_cockpit.get_issue_promotion_context", {
		issue: frm.doc.name,
	});
	if (context.project) {
		return run_promotion(frm.doc.name, context.project);
	}
	const options = (context.projects || []).map((project) => project.name).join("\n");
	const dialog = new frappe.ui.Dialog({
		title: __("Issue in Task übernehmen"),
		fields: [
			{
				fieldname: "project",
				fieldtype: "Select",
				label: __("Project"),
				options,
				reqd: 1,
			},
		],
		primary_action_label: __("Create Task"),
		primary_action: async (values) => {
			dialog.hide();
			await run_promotion(frm.doc.name, values.project);
		},
	});
	dialog.show();
}

async function run_promotion(issue, project) {
	const result = await frappe.xcall("working_time.work_cockpit.promote_issue_to_task", {
		issue,
		project,
	});
	frappe.show_alert({
		message: result.created ? __("Task created") : __("Existing Task opened"),
		indicator: "green",
	});
	window.location.href = result.route;
}
