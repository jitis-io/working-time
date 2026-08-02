// Copyright (c) 2023, ALYF GmbH and contributors
// For license information, please see license.txt

frappe.ui.form.on("Working Time", {
	setup: function (frm) {
		frm.set_query("employee", "erpnext.controllers.queries.employee_query");
	},
	refresh: function (frm) {
		if (frm.doc.docstatus === 0) {
			// Linked documents will get created on submit.
			// Hide the dashboard if the document is not yet submitted.
			frm.dashboard.hide();
			frm.trigger("show_stats");
		} else {
			frm.trigger("hide_stats");
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
	date: function (frm) {
		frm.trigger("show_stats");
	},
	employee: function (frm) {
		frm.trigger("show_stats");
	},
	show_stats: function (frm) {
		if (!frm.doc.employee || !frm.doc.date) {
			frm.trigger("hide_stats");
			return;
		}

		frappe
			.xcall(
				"working_time.working_time.doctype.working_time.working_time.get_working_time_stats",
				{ employee: frm.doc.employee, date: frm.doc.date }
			)
			.then((message) => {
				if (message) {
					frm.set_df_property("stats_section", "hidden", 0);
					frm.set_df_property(
						"stats_html",
						"options",
						frappe.render_template("working_time_dashboard", {
							data: message,
						})
					);
					frm.refresh_field("stats_html");
				}
			});
	},
	hide_stats: function (frm) {
		frm.set_df_property("stats_html", "options", "");
		frm.set_df_property("stats_section", "hidden", 1);
		frm.refresh_field("stats_html");
	},
});

frappe.ui.form.on("Working Time Log", {
	project: function (frm, cdt, cdn) {
		const child = locals[cdt][cdn];
		frappe.db
			.get_value("Project", child.project, ["project_type", "billing_model"])
			.then(({ message }) => {
				if (message && (message.project_type === "Internal" || message.billing_model !== "Time and Material")) {
					frappe.model.set_value(cdt, cdn, "billable", "0%");
				} else {
					frappe.model.set_value(cdt, cdn, "billable", "100%");
				}
			});
	},
});
