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
			frappe.prompt(
				[
					{
						fieldname: "preview",
						fieldtype: "HTML",
						options: `<pre>${frappe.utils.escape_html(details)}</pre>`,
					},
					{
						fieldname: "billing_model",
						fieldtype: "Select",
						label: __("Billing Model"),
						options: ["", ...(result.preview.billing_models || [])].join("\n"),
						reqd: 1,
					},
					{
						fieldname: "billing_rate",
						fieldtype: "Currency",
						label: __("Billing Rate per Hour"),
						default: result.preview.suggested_billing_rate || 0,
						depends_on: 'eval:doc.billing_model==="Time and Material"',
						mandatory_depends_on: 'eval:doc.billing_model==="Time and Material"',
					},
				],
				async (values) => {
					await frappe.call({
						method: "working_time.platform_operations.confirm_customer_project_provisioning",
						args: {
							provisioning_name: result.name,
							billing_model: values.billing_model,
							billing_rate: values.billing_rate,
						},
						freeze: true,
						freeze_message: __("Queueing provisioning…"),
					});
					frappe.set_route(
						"Form",
						"Customer Project Provisioning",
						result.name
					);
				},
				__("Project provision"),
				__("Queue provisioning")
			);
		});
	},
});
