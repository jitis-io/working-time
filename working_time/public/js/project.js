frappe.ui.form.on("Project", {
	async refresh(frm) {
		if (frm.is_new()) return;
		const context = await frappe.xcall("working_time.work_cockpit.get_project_commercial_context", {
			project: frm.doc.name,
		});
		if (context.contract) {
			frm.add_custom_button(__("Contract"), () => frappe.set_route("Form", "Contract", context.contract), __("Commercial"));
		}
		if (context.sales_order) {
			frm.add_custom_button(__("Sales Order"), () => frappe.set_route("Form", "Sales Order", context.sales_order), __("Commercial"));
		}
		for (const invoice of context.sales_invoices || []) {
			frm.add_custom_button(invoice, () => frappe.set_route("Form", "Sales Invoice", invoice), __("Sales Invoices"));
		}
	},
});
