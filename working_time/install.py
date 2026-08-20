# Copyright (c) 2023, ALYF GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

OBSOLETE_CUSTOM_FIELDS = {
	# The legacy Sales Order field is retired conditionally by its data-preserving patch.
	"Customer": [
		"customer_offboarding",
	],
	"Task": [
		"working_time_issue_attachments_html",
	],
	"Timesheet Detail": [
		"jira_section",
		"jira",
		"issue_url",
	],
}


def after_install():
	make_custom_fields()
	migrate_project_time_billing()
	insert_docs()
	migrate_legacy_settings()
	retire_legacy_navigation()
	update_projects_settings()
	backfill_customer_projects()


def after_migrate():
	make_custom_fields()
	migrate_project_time_billing()
	insert_docs()
	migrate_legacy_settings()
	retire_legacy_navigation()
	backfill_customer_projects()


def retire_legacy_navigation():
	"""Remove the superseded parallel work surfaces without touching business records."""

	for doctype, name in (
		("Workspace", "Platform Operations"),
		("Workspace", "Time Tracking"),
		("Workspace Sidebar", "Platform Operations"),
		("Workspace Sidebar", "Time Tracking"),
		("Desktop Icon", "Platform Operations"),
		("Desktop Icon", "Time Tracking"),
		("Page", "work-cockpit"),
		("Page", "working-time-quick-entry"),
		("Number Card", "Daily Billable Time (this month)"),
		("Number Card", "Daily Break Time (this month)"),
		("Number Card", "Daily Project Time (this month)"),
		("Number Card", "Working Time (this month)"),
	):
		if not frappe.db.exists("DocType", doctype):
			continue
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)


def migrate_legacy_settings():
	"""Keep the configured billing item while retiring Platform Operations from daily use."""

	if not frappe.db.exists("DocType", "Platform Operations Settings"):
		return
	current = frappe.db.get_single_value("Working Time Settings", "default_time_billing_item")
	legacy = frappe.db.get_single_value("Platform Operations Settings", "default_time_billing_item")
	if legacy and not current:
		frappe.db.set_single_value("Working Time Settings", "default_time_billing_item", legacy)


def migrate_project_time_billing():
	"""Map the legacy four-way billing model to the simple visible time switch."""

	if not frappe.db.has_column("Project", "time_billable"):
		return
	frappe.db.sql(
		"""
		update `tabProject`
		set time_billable = 1
		where billing_model = 'Time and Material'
			and coalesce(time_billable, 0) = 0
		"""
	)


def backfill_customer_projects():
	if not frappe.is_setup_complete():
		return
	from working_time.customer_projects import backfill_customer_projects as backfill_customers
	from working_time.customer_projects import backfill_issue_projects

	backfill_customers()
	backfill_issue_projects()


def make_custom_fields():
	create_custom_fields(frappe.get_hooks("working_time_custom_fields"))
	delete_obsolete_custom_fields()


def delete_obsolete_custom_fields():
	for doctype, fieldnames in OBSOLETE_CUSTOM_FIELDS.items():
		changed = False
		for fieldname in fieldnames:
			custom_field_name = f"{doctype}-{fieldname}"
			if frappe.db.exists("Custom Field", custom_field_name):
				frappe.delete_doc("Custom Field", custom_field_name, ignore_permissions=True, force=True)
				changed = True
		if changed:
			frappe.clear_cache(doctype=doctype)


def insert_docs():
	docs = [
		{
			"doctype": "Activity Type",
			"activity_type": "Default",
		},
		{
			"doctype": "Project Type",
			"project_type": "Internal",
		},
	]

	for doc in docs:
		filters = doc.copy()

		# Clean up filters. They need to be a plain dict without nested dicts or lists.
		for key, value in doc.items():
			if isinstance(value, list | dict):
				del filters[key]

		if not frappe.db.exists(filters):
			frappe.get_doc(doc).insert(ignore_if_duplicate=True)


def update_projects_settings():
	if frappe.is_setup_complete():
		# don't mess with settings in preexisting sites
		return

	settings = frappe.get_single("Projects Settings")
	settings.update(
		{
			"ignore_user_time_overlap": 1,
			"ignore_employee_time_overlap": 1,
		}
	)
	settings.save()
