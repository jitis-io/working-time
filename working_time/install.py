# Copyright (c) 2023, ALYF GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

OBSOLETE_CUSTOM_FIELDS = {
	"Customer": [
		"customer_offboarding",
	],
	"Timesheet Detail": [
		"jira_section",
		"jira",
		"issue_url",
	],
}


def after_install():
	make_custom_fields()
	insert_docs()
	ensure_work_cockpit_metadata()
	update_projects_settings()


def after_migrate():
	make_custom_fields()
	insert_docs()
	ensure_work_cockpit_metadata()


def ensure_work_cockpit_metadata():
	"""Force-sync the app-owned Desk metadata on existing sites.

	Frappe can retain a newer database copy of a standard Workspace during an
	upgrade. Reloading both documents keeps the stable Work Cockpit route and
	its Platform Operations link present without editing user-owned records.
	"""
	frappe.reload_doc("working_time", "page", "work_cockpit", force=True)
	frappe.reload_doc("working_time", "workspace", "platform_operations", force=True)


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
