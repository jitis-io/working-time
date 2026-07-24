frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (
			frm.doc.docstatus !== 1 ||
			!frappe.user.has_role("System Manager")
		) {
			return;
		}

		frm.add_custom_button(__("Project provision"), async () => {
			const preview = await frappe.call({
				method: "working_time.platform_operations.prepare_customer_project_provisioning",
				args: { sales_order_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Preparing project provisioning…"),
			});
			const result = preview.message;
			const details = JSON.stringify(result.preview || {}, null, 2);
			frappe.confirm(
				__(
					"Provision the ERPNext and OpenProject projects for this Sales Order?<br><br><pre>{0}</pre>",
					[frappe.utils.escape_html(details)]
				),
				async () => {
					await frappe.call({
						method: "working_time.platform_operations.confirm_customer_project_provisioning",
						args: { provisioning_name: result.name },
						freeze: true,
						freeze_message: __("Queueing provisioning…"),
					});
					frappe.set_route(
						"Form",
						"Customer Project Provisioning",
						result.name
					);
				}
			);
		});
	},
});
