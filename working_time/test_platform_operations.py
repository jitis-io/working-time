import sys
import types
import unittest
from unittest.mock import patch


def _bootstrap_frappe_stub() -> None:
	if "frappe" in sys.modules:
		return

	def throw(message):
		raise RuntimeError(message)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda message: message
	frappe.throw = throw
	frappe.only_for = lambda *args, **kwargs: None
	frappe.RetryBackgroundJobError = type("RetryBackgroundJobError", (Exception,), {})
	frappe.whitelist = lambda *args, **kwargs: lambda fn: fn
	frappe.db = types.SimpleNamespace(get_value=lambda *args, **kwargs: None)
	frappe.get_all = lambda *args, **kwargs: []
	frappe.get_doc = lambda *args, **kwargs: None
	frappe.get_single = lambda *args, **kwargs: None
	frappe.enqueue = lambda *args, **kwargs: None
	sys.modules["frappe"] = frappe


_bootstrap_frappe_stub()

from working_time.keycloak_client import customer_group_name
from working_time.platform_operations import (
	_dispatch_openproject_event,
	_reconciliation_function,
	_sales_order_project_name,
)


class TestPlatformOperations(unittest.TestCase):
	def test_customer_group_name_is_stable_and_safe(self):
		self.assertEqual(
			customer_group_name("K-2601002 / Müller GmbH", "customer-"),
			"customer-k-2601002-m-ller-gmbh-a466b0ce",
		)
		self.assertEqual(customer_group_name("Customer", ""), "customer-customer-0e85749a")

	def test_dispatches_time_entry_update_to_existing_sync(self):
		event = types.SimpleNamespace(
			action="time_entry:updated",
			object_id="42",
			openproject_site="OpenProject",
			payload_json='{"action": "time_entry:updated"}',
		)
		with patch(
			"working_time.openproject_sync.sync_time_entry_from_openproject", return_value={"updated": True}
		) as sync:
			self.assertEqual(_dispatch_openproject_event(event), {"updated": True})

		sync.assert_called_once_with("42", "OpenProject")

	def test_dispatches_deleted_work_package_to_delete_worker(self):
		event = types.SimpleNamespace(
			action="work_package:deleted",
			object_id="99",
			openproject_site="OpenProject",
			payload_json='{"action": "work_package:deleted"}',
		)
		with patch(
			"working_time.openproject_sync.delete_work_package_from_openproject",
			return_value={"deleted": True},
		) as delete:
			self.assertEqual(_dispatch_openproject_event(event), {"deleted": True})

		delete.assert_called_once_with("99")

	def test_sales_order_project_name_preserves_customer_context(self):
		sales_order = types.SimpleNamespace(
			customer_name="Example GmbH", customer="CUST-0001", name="SO-0001"
		)
		self.assertEqual(_sales_order_project_name(sales_order), "Example GmbH — SO-0001")

	def test_reconciliation_type_uses_the_expected_existing_function(self):
		function = _reconciliation_function("Time Entries")
		self.assertEqual(function.__name__, "reconcile_openproject_time_entries")

	def test_unknown_reconciliation_type_is_rejected(self):
		with self.assertRaises(RuntimeError):
			_reconciliation_function("Unknown")
