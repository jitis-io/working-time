import frappe
from frappe.tests import IntegrationTestCase

from working_time.patches.v1_3_migrate import execute


class TestV13Migration(IntegrationTestCase):
	def test_missing_billing_model_is_created_before_backfill(self):
		custom_field = "Project-billing_model"
		if frappe.db.exists("Custom Field", custom_field):
			frappe.delete_doc("Custom Field", custom_field, ignore_permissions=True, force=True)
		if frappe.db.has_column("Project", "billing_model"):
			frappe.db.sql_ddl("alter table `tabProject` drop column `billing_model`")
		frappe.clear_cache(doctype="Project")

		self.assertFalse(frappe.db.has_column("Project", "billing_model"))

		execute()

		self.assertTrue(frappe.db.exists("Custom Field", custom_field))
		self.assertTrue(frappe.db.has_column("Project", "billing_model"))
