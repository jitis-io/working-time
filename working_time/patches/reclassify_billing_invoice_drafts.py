import frappe


def execute():
	"""Correct reviews that used the old Invoiced status for draft invoices."""
	for review_name in frappe.get_all("Billing Review", filters={"status": "Invoiced"}, pluck="name"):
		items = frappe.get_all(
			"Billing Review Item",
			filters={"parent": review_name, "sales_invoice": ["is", "set"]},
			fields=["name", "sales_invoice", "status"],
		)
		if not items:
			continue

		all_submitted = True
		for item in items:
			submitted = int(frappe.db.get_value("Sales Invoice", item.sales_invoice, "docstatus") or 0) == 1
			status = "Invoiced" if submitted else "Draft Created"
			all_submitted = all_submitted and submitted
			if item.status != status:
				frappe.db.set_value(
					"Billing Review Item",
					item.name,
					"status",
					status,
					update_modified=False,
				)

		if not all_submitted:
			frappe.db.set_value(
				"Billing Review",
				review_name,
				"status",
				"Draft Created",
				update_modified=False,
			)
