import sys
import types
import unittest
from unittest.mock import call, patch

from working_time.test_platform_operations import _bootstrap_frappe_stub

_bootstrap_frappe_stub()

import frappe


def _bootstrap_custom_field_stub() -> None:
	custom_field_module = "frappe.custom.doctype.custom_field.custom_field"
	if getattr(frappe, "__file__", None) or custom_field_module in sys.modules:
		return
	for module_name in (
		"frappe.custom",
		"frappe.custom.doctype",
		"frappe.custom.doctype.custom_field",
	):
		module = sys.modules.setdefault(module_name, types.ModuleType(module_name))
		module.__path__ = []
	custom_field = types.ModuleType(custom_field_module)
	custom_field.create_custom_fields = lambda *args, **kwargs: None
	sys.modules[custom_field.__name__] = custom_field


_bootstrap_custom_field_stub()

from working_time.install import OBSOLETE_CUSTOM_FIELDS
from working_time.patches.correct_customer_project_name import (
	CORRECT_PROJECT_NAME,
	CUSTOMER,
	PROJECT,
	WRONG_PROJECT_NAME,
)
from working_time.patches.correct_customer_project_name import (
	execute as correct_customer_project_name,
)
from working_time.patches.retire_sales_order_provisioning import (
	CHILD_DOCTYPE,
	PARENT_DOCTYPE,
	SALES_ORDER_FIELD,
)
from working_time.patches.retire_sales_order_provisioning import (
	execute as retire_sales_order_provisioning,
)


class FakeDocument(types.SimpleNamespace):
	pass


class TestCustomerProjectPatches(unittest.TestCase):
	def test_exact_live_project_name_correction_is_idempotent(self):
		states = iter(
			[
				FakeDocument(project_name=WRONG_PROJECT_NAME, customer=CUSTOMER),
				FakeDocument(project_name=CORRECT_PROJECT_NAME, customer=CUSTOMER),
			]
		)

		def get_value(doctype, filters, fieldname, **kwargs):
			self.assertEqual(doctype, "Project")
			if filters == PROJECT:
				self.assertEqual(fieldname, ["project_name", "customer"])
				self.assertEqual(kwargs, {"as_dict": True})
				return next(states)
			self.assertEqual(
				filters,
				{"project_name": CORRECT_PROJECT_NAME, "name": ("!=", PROJECT)},
			)
			self.assertEqual(fieldname, "name")
			return None

		with (
			patch(
				"working_time.patches.correct_customer_project_name.frappe.db.get_value",
				side_effect=get_value,
			),
			patch("working_time.patches.correct_customer_project_name.frappe.db.set_value") as set_value,
		):
			correct_customer_project_name()
			correct_customer_project_name()

		set_value.assert_called_once_with(
			"Project",
			PROJECT,
			"project_name",
			CORRECT_PROJECT_NAME,
			update_modified=False,
		)

	def test_live_project_name_correction_checks_conflict_before_write(self):
		state = FakeDocument(project_name=WRONG_PROJECT_NAME, customer=CUSTOMER)
		with (
			patch(
				"working_time.patches.correct_customer_project_name.frappe.db.get_value",
				side_effect=[state, "PROJ-CONFLICT"],
			),
			patch("working_time.patches.correct_customer_project_name.frappe.db.set_value") as set_value,
			self.assertRaisesRegex(
				frappe.ValidationError,
				f"Cannot correct {PROJECT}: project name {CORRECT_PROJECT_NAME} is already used by PROJ-CONFLICT",
			),
		):
			correct_customer_project_name()

		set_value.assert_not_called()

	def test_live_project_name_correction_refuses_unverified_state(self):
		states = (
			None,
			FakeDocument(project_name=WRONG_PROJECT_NAME, customer="CUST-OTHER"),
			FakeDocument(project_name="Unexpected Name", customer=CUSTOMER),
		)
		for state in states:
			with (
				self.subTest(state=state),
				patch(
					"working_time.patches.correct_customer_project_name.frappe.db.get_value",
					return_value=state,
				) as get_value,
				patch("working_time.patches.correct_customer_project_name.frappe.db.set_value") as set_value,
			):
				correct_customer_project_name()

			get_value.assert_called_once_with(
				"Project",
				PROJECT,
				["project_name", "customer"],
				as_dict=True,
			)
			set_value.assert_not_called()

	def test_historical_sales_order_provisioning_is_preserved(self):
		with (
			patch(
				"working_time.patches.retire_sales_order_provisioning.frappe.db.exists",
				return_value=True,
			),
			patch(
				"working_time.patches.retire_sales_order_provisioning.frappe.db.count",
				return_value=1,
				create=True,
			),
			patch(
				"working_time.patches.retire_sales_order_provisioning.frappe.delete_doc",
				create=True,
			) as delete_doc,
			patch(
				"working_time.patches.retire_sales_order_provisioning.frappe.clear_cache",
				create=True,
			) as clear_cache,
		):
			retire_sales_order_provisioning()

		delete_doc.assert_not_called()
		clear_cache.assert_not_called()
		self.assertNotIn("Sales Order", OBSOLETE_CUSTOM_FIELDS)

	def test_empty_sales_order_provisioning_metadata_is_retired(self):
		def exists(doctype, name):
			return (doctype, name) in {
				("DocType", PARENT_DOCTYPE),
				("DocType", CHILD_DOCTYPE),
				("Custom Field", SALES_ORDER_FIELD),
			}

		with (
			patch(
				"working_time.patches.retire_sales_order_provisioning.frappe.db.exists",
				side_effect=exists,
			),
			patch(
				"working_time.patches.retire_sales_order_provisioning.frappe.db.count",
				return_value=0,
				create=True,
			),
			patch(
				"working_time.patches.retire_sales_order_provisioning.frappe.delete_doc",
				create=True,
			) as delete_doc,
			patch(
				"working_time.patches.retire_sales_order_provisioning.frappe.clear_cache",
				create=True,
			) as clear_cache,
		):
			retire_sales_order_provisioning()

		self.assertEqual(
			delete_doc.call_args_list,
			[
				call("Custom Field", SALES_ORDER_FIELD, ignore_permissions=True, force=True),
				call(
					"DocType",
					PARENT_DOCTYPE,
					ignore_permissions=True,
					ignore_missing=True,
					force=True,
				),
				call(
					"DocType",
					CHILD_DOCTYPE,
					ignore_permissions=True,
					ignore_missing=True,
					force=True,
				),
			],
		)
		clear_cache.assert_called_once_with()


if __name__ == "__main__":
	unittest.main()
