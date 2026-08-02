import frappe

RETIRED_DOCTYPES = (
	"OpenProject Webhook Event",
	"OpenProject Reconciliation Run",
	"OpenProject Sync Tombstone",
	"OpenProject Site",
)

RETIRED_COLUMNS = {
	"Customer Project Provisioning": (
		"openproject_project_id",
		"openproject_site",
		"openproject_url",
	),
	"Project": (
		"openproject_last_synced_at",
		"openproject_phase_work_package_id",
		"openproject_project_id",
		"openproject_project_work_package_id",
		"openproject_site",
		"openproject_url",
	),
	"Task": (
		"openproject_last_synced_at",
		"openproject_url",
		"openproject_work_package_id",
		"openproject_work_package_url_task",
	),
	"Timesheet": ("openproject_last_synced_at",),
	"Timesheet Detail": (
		"openproject_time_entry_id",
		"openproject_time_entry_url",
		"openproject_work_package_url",
	),
}


def execute():
	for doctype in RETIRED_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		# Delete the DocType itself so Frappe drops its table and records without
		# importing the retired controller, which is intentionally absent from
		# this release.
		frappe.delete_doc(
			"DocType",
			doctype,
			ignore_permissions=True,
			ignore_missing=True,
			force=True,
		)

	for name in frappe.get_all(
		"Custom Field",
		filters={"fieldname": ("like", "openproject%")},
		pluck="name",
	):
		frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)

	for doctype, columns in RETIRED_COLUMNS.items():
		if not frappe.db.table_exists(doctype, cached=False):
			continue
		for column in columns:
			if frappe.db.has_column(doctype, column):
				frappe.db.sql_ddl(f"ALTER TABLE `tab{doctype}` DROP COLUMN `{column}`")

	for doctype in RETIRED_DOCTYPES:
		if frappe.db.table_exists(doctype, cached=False):
			frappe.db.sql_ddl(f"DROP TABLE `tab{doctype}`")

	if frappe.db.exists("Workspace", "Integration Control Center"):
		frappe.delete_doc("Workspace", "Integration Control Center", ignore_permissions=True, force=True)

	if frappe.db.exists("DocType", "Scheduled Job Type"):
		frappe.db.delete("Scheduled Job Type", {"method": ("like", "%openproject%")})
	if frappe.db.exists("DocType", "Platform Alert"):
		frappe.db.delete("Platform Alert", {"source": ("like", "openproject%")})
	frappe.clear_cache()
