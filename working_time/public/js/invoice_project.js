(() => {
	"use strict";

	for (const doctype of ["Purchase Invoice", "Sales Invoice"]) {
		frappe.ui.form.on(doctype, {
			onload(frm) {
				apply_route_project(frm);
				show_item_project(frm);
			},
			refresh(frm) {
				apply_route_project(frm);
				show_item_project(frm);
			},
			project(frm) {
				show_item_project(frm);
			},
			items_on_form_rendered(frm) {
				show_item_project(frm);
			},
		});
	}

	async function apply_route_project(frm) {
		if (!frm.is_new() || frm.doc.project || frm.__working_time_route_project_pending) return;
		if (!frappe.meta.has_field(frm.doctype, "project")) return;
		const project = frappe.utils.get_url_arg("project") || frappe.route_options?.project;
		if (!project) return;
		frm.__working_time_route_project_pending = true;
		try {
			await frm.set_value("project", String(project));
		} catch (error) {
			frappe.msgprint({
				title: __(frm.doctype),
				message: frappe.utils.escape_html(
					String(error?.message || __("The project could not be applied."))
				),
				indicator: "red",
			});
		} finally {
			frm.__working_time_route_project_pending = false;
		}
	}

	function show_item_project(frm) {
		const grid = frm.fields_dict.items?.grid;
		if (!grid?.get_docfield("project")) return;
		grid.update_docfield_property("project", "hidden", 0);
		grid.update_docfield_property("project", "in_list_view", 1);
		grid.update_docfield_property("project", "columns", 2);
		if (typeof grid.set_column_disp_in_list_view === "function") {
			grid.set_column_disp_in_list_view("project", true);
		} else if (typeof grid.set_column_disp === "function") {
			grid.set_column_disp("project", true);
		}
	}
})();
