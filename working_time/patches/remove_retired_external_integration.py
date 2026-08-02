import frappe

RETIRED_DOCTYPES = (
	"OpenProject Webhook Event",
	"OpenProject Reconciliation Run",
	"OpenProject Sync Tombstone",
	"OpenProject Site",
)

RETIRED_CUSTOM_FIELDS = {
	"Project": ("openproject_section", "openproject_site", "openproject_url", "openproject_project_id"),
	"Task": ("openproject_url", "openproject_work_package_id"),
	"Timesheet Detail": (
		"openproject_section",
		"openproject_time_entry_url",
		"openproject_work_package_url",
		"openproject_time_entry_id",
	),
}


def execute():
	for doctype in RETIRED_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		for name in frappe.get_all(doctype, pluck="name"):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)

	for doctype, fieldnames in RETIRED_CUSTOM_FIELDS.items():
		for fieldname in fieldnames:
			name = f"{doctype}-{fieldname}"
			if frappe.db.exists("Custom Field", name):
				frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

	if frappe.db.exists("Workspace", "Integration Control Center"):
		frappe.delete_doc("Workspace", "Integration Control Center", ignore_permissions=True, force=True)

	if frappe.db.exists("DocType", "Scheduled Job Type"):
		frappe.db.delete("Scheduled Job Type", {"method": ("like", "%openproject%")})
	if frappe.db.exists("DocType", "Platform Alert"):
		frappe.db.delete("Platform Alert", {"source": ("like", "openproject%")})
	frappe.clear_cache()
