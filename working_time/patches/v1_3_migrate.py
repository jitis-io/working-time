import frappe

from working_time.install import make_custom_fields

TASK_FIELDS = ("custom_is_active", "custom_hourly_billed")


def execute():
	# Existing sites have already recorded the older generic custom-field patch.
	# Create the v1.3 fields explicitly before any backfill queries them.
	make_custom_fields()
	migrate_project_sales_orders()
	backfill_project_billing_models()
	backfill_workdays()
	migrate_draft_notes()
	remove_orphan_task_fields()
	remove_source_sales_order_field()


def migrate_project_sales_orders():
	if not frappe.db.has_column("Project", "source_sales_order"):
		return
	for project in frappe.get_all("Project", fields=["name", "source_sales_order", "sales_order"]):
		if not project.source_sales_order:
			continue
		if project.sales_order and project.sales_order != project.source_sales_order:
			frappe.throw(f"Project {project.name} has conflicting sales orders")
		if not project.sales_order:
			frappe.db.set_value(
				"Project", project.name, "sales_order", project.source_sales_order, update_modified=False
			)


def backfill_project_billing_models():
	for project in frappe.get_all(
		"Project", fields=["name", "project_type", "sales_order", "billing_rate", "billing_model"]
	):
		model = "Non-billable"
		if (
			project.project_type != "Internal"
			and project.sales_order
			and float(project.billing_rate or 0) > 0
		):
			model = "Time and Material"
		frappe.db.set_value("Project", project.name, "billing_model", model, update_modified=False)


def backfill_workdays():
	rows = frappe.db.sql(
		"""select parent, min(from_time), max(to_time),
		sum(case when is_break = 1 then coalesce(duration, 0) else 0 end)
		from `tabWorking Time Log` where from_time is not null or to_time is not null group by parent""",
		as_list=True,
	)
	for name, check_in, check_out, indicated_break in rows:
		values = {"indicated_break": indicated_break or 0}
		if check_in:
			values["check_in"] = check_in
		if check_out:
			values["check_out"] = check_out
		frappe.db.set_value("Working Time", name, values, update_modified=False)


def migrate_draft_notes():
	rows = frappe.db.sql(
		"""select log.name, log.note from `tabWorking Time Log` log
		join `tabWorking Time` parent on parent.name = log.parent
		where parent.docstatus = 0 and coalesce(log.note, '') != ''
		and coalesce(log.customer_description, '') = '' and coalesce(log.internal_note, '') = ''""",
		as_dict=True,
	)
	for row in rows:
		note = row.note.strip()
		values = (
			{"customer_description": note[1:].strip()} if note.startswith("+") else {"internal_note": note}
		)
		frappe.db.set_value("Working Time Log", row.name, values, update_modified=False)


def remove_orphan_task_fields():
	references = []
	search_targets = {
		"Client Script": ("script",),
		"Server Script": ("script",),
		"Report": ("query", "javascript", "json"),
		"Print Format": ("html", "css"),
	}
	for doctype, fields in search_targets.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		for fieldname in fields:
			if not meta.has_field(fieldname):
				continue
			for task_field in TASK_FIELDS:
				matches = frappe.get_all(
					doctype, filters={fieldname: ("like", f"%{task_field}%")}, pluck="name"
				)
				references.extend(f"{doctype} {name}" for name in matches)
	if references:
		frappe.throw("Task field cleanup aborted; references found: " + ", ".join(sorted(set(references))))
	for fieldname in TASK_FIELDS:
		name = f"Task-{fieldname}"
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)


def remove_source_sales_order_field():
	name = "Project-source_sales_order"
	if frappe.db.exists("Custom Field", name):
		frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
