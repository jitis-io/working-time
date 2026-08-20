frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.is_new()) return;
		let running = false;
		const button = frm.add_custom_button(__("Customer project"), async () => {
			if (running) return;
			running = true;
			button.prop("disabled", true).attr("aria-busy", "true");
			try {
				const result = await frappe.xcall(
					"working_time.customer_projects.ensure_customer_project",
					{ customer: frm.doc.name }
				);
				if (!result?.project) throw new Error(__("No customer project is available."));
				if (result.created) {
					frappe.show_alert({ message: __("Customer project created"), indicator: "green" });
				} else if (result.reopened) {
					frappe.show_alert({ message: __("Customer project reopened"), indicator: "green" });
				}
				frappe.set_route("Form", "Project", result.project);
			} catch (error) {
				frappe.msgprint({
					title: __("Customer project"),
					message: window.working_time.safe_error(
						error,
						__("The customer project could not be opened.")
					),
					indicator: "red",
				});
			} finally {
				running = false;
				button.prop("disabled", false).removeAttr("aria-busy");
			}
		});
	},
});
