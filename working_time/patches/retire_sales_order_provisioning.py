import frappe

PARENT_DOCTYPE = "Customer Project Provisioning"
CHILD_DOCTYPE = "Customer Project Provisioning Step"
SALES_ORDER_FIELD = "Sales Order-customer_project_provisioning"


def execute():
	"""Drop the retired per-Sales-Order workflow only when it contains no records."""

	if not frappe.db.exists("DocType", PARENT_DOCTYPE):
		return
	if frappe.db.count(PARENT_DOCTYPE):
		# Historical records are never deleted automatically. Such a site keeps
		# the legacy metadata read-only until it is archived explicitly.
		return

	if frappe.db.exists("Custom Field", SALES_ORDER_FIELD):
		frappe.delete_doc("Custom Field", SALES_ORDER_FIELD, ignore_permissions=True, force=True)

	frappe.delete_doc(
		"DocType",
		PARENT_DOCTYPE,
		ignore_permissions=True,
		ignore_missing=True,
		force=True,
	)
	if frappe.db.exists("DocType", CHILD_DOCTYPE):
		frappe.delete_doc(
			"DocType",
			CHILD_DOCTYPE,
			ignore_permissions=True,
			ignore_missing=True,
			force=True,
		)
	frappe.clear_cache()
