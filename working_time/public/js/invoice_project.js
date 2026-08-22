(() => {
	"use strict";

	for (const doctype of ["Purchase Invoice", "Sales Invoice"]) {
		frappe.ui.form.on(doctype, {
			onload(frm) {
				apply_route_project(frm);
			},
			refresh(frm) {
				apply_route_project(frm);
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
				message: window.working_time.safe_error(
					error,
					__("The project could not be applied.")
				),
				indicator: "red",
			});
		} finally {
			frm.__working_time_route_project_pending = false;
		}
	}
})();
