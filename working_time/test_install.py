from unittest import TestCase

import frappe

from working_time.install import insert_docs, make_custom_fields, retire_legacy_navigation


class TestInstall(TestCase):
	def test_internal_project_type_is_provisioned_idempotently(self):
		if frappe.db.exists("Project Type", "Internal"):
			frappe.delete_doc("Project Type", "Internal", force=True)

		insert_docs()
		insert_docs()

		self.assertEqual(frappe.db.count("Project Type", {"project_type": "Internal"}), 1)

	def test_legacy_parallel_navigation_is_retired_idempotently(self):
		retire_legacy_navigation()
		retire_legacy_navigation()

		for doctype, name in (
			("Workspace", "Platform Operations"),
			("Workspace", "Time Tracking"),
			("Page", "work-cockpit"),
			("Page", "working-time-quick-entry"),
			("Number Card", "Daily Billable Time (this month)"),
			("Number Card", "Daily Break Time (this month)"),
			("Number Card", "Daily Project Time (this month)"),
			("Number Card", "Working Time (this month)"),
		):
			self.assertFalse(frappe.db.exists(doctype, name))

	def test_project_customer_account_fields_are_idempotent(self):
		make_custom_fields()
		make_custom_fields()

		meta = frappe.get_meta("Project")
		fieldnames = [field.fieldname for field in meta.fields]
		expected_order = [
			"customer_account_tab",
			"customer_account_settings_section",
			"time_billable",
			"billing_model",
			"billing_rate",
			"customer_account_settings_column",
			"contract",
			"customer_account_overview_section",
			"customer_account_overview",
		]
		self.assertEqual(
			[fieldname for fieldname in fieldnames if fieldname in expected_order],
			expected_order,
		)
		self.assertEqual(meta.get_field("customer_account_tab").fieldtype, "Tab Break")
		self.assertEqual(meta.get_field("customer_account_settings_section").fieldtype, "Section Break")
		self.assertEqual(meta.get_field("customer_account_settings_column").fieldtype, "Column Break")
		self.assertEqual(meta.get_field("customer_account_overview_section").fieldtype, "Section Break")
		self.assertTrue(meta.has_field("customer_account_overview"))
		self.assertTrue(meta.has_field("time_billable"))
		self.assertTrue(frappe.get_meta("Customer").has_field("customer_project"))
