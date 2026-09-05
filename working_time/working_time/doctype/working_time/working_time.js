// Copyright (c) 2023, ALYF GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Working Time", {
	setup: function (frm) {
		frm.set_query("employee", "erpnext.controllers.queries.employee_query");
	},
	refresh: function (frm) {
		if (frm.doc.docstatus === 0) {
			frm.set_intro(__(
				"Close the whole workday: enter start, end and break, and allocate all net time. Book administration and acquisition to your internal Project. Review customer descriptions and mark included Care time as non-billable. Submission creates native Timesheets and Attendance; it does not invoice or send anything."
			), "blue");
			// Linked documents will get created on submit.
			// Hide the dashboard if the document is not yet submitted.
			frm.dashboard.hide();
		}

		if (frm.is_new() && !frm.doc.employee) {
			frm.trigger("set_employee");
		}
	},
	// set employee (and company) to the one that's currently logged in
	set_employee: function (frm) {
		frappe.db
			.get_value("Employee", { user_id: frappe.session.user }, "name")
			.then(({ message }) => {
				if (message) {
					frm.set_value("employee", message.name);
				}
			});
	},
});

frappe.ui.form.on("Working Time Log", {
	project: function (frm, cdt, cdn) {
		const child = locals[cdt][cdn];
		frappe.db
			.get_value("Project", child.project, ["project_type", "time_billable"])
			.then(({ message }) => {
				if (message && (message.project_type === "Internal" || !message.time_billable)) {
					frappe.model.set_value(cdt, cdn, "billable", "0%");
				} else {
					frappe.model.set_value(cdt, cdn, "billable", "100%");
				}
			});
	},
});
