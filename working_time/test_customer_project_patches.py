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


def _bootstrap_document_stub() -> None:
	document_module = "frappe.model.document"
	if getattr(frappe, "__file__", None) or document_module in sys.modules:
		return
	for module_name in ("frappe.model",):
		module = sys.modules.setdefault(module_name, types.ModuleType(module_name))
		module.__path__ = []
	document = types.ModuleType(document_module)
	document.Document = type("Document", (), {})
	sys.modules[document.__name__] = document


_bootstrap_document_stub()

from frappe.model.document import Document

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
from working_time.patches.synchronize_billing_review_statuses import (
	execute as synchronize_billing_review_statuses,
)
from working_time.working_time.doctype.customer_project_provisioning.customer_project_provisioning import (
	CustomerProjectProvisioning,
)
from working_time.working_time.doctype.customer_project_provisioning_step.customer_project_provisioning_step import (
	CustomerProjectProvisioningStep,
)


class FakeDocument(types.SimpleNamespace):
	pass


class TestCustomerProjectPatches(unittest.TestCase):
	def test_billing_review_status_patch_is_scoped_and_idempotent(self):
		linked = FakeDocument(sales_invoice="SINV-0001")
		review = FakeDocument(name="BR-0001", items=[linked])
		with (
			patch(
				"working_time.patches.synchronize_billing_review_statuses.frappe.db.exists",
				return_value=True,
			),
			patch(
				"working_time.patches.synchronize_billing_review_statuses.frappe.get_all",
				return_value=["BR-0001"],
			) as get_all,
			patch(
				"working_time.patches.synchronize_billing_review_statuses.frappe.get_doc",
				return_value=review,
			),
			patch(
				"working_time.patches.synchronize_billing_review_statuses._synchronize_billing_review_status"
			) as synchronize,
		):
			synchronize_billing_review_statuses()
			synchronize_billing_review_statuses()

		get_all.assert_called_with(
			"Billing Review",
			pluck="name",
		)
		self.assertEqual(synchronize.call_count, 2)
		synchronize.assert_called_with(review)

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
		self.assertTrue(issubclass(CustomerProjectProvisioning, Document))
		self.assertTrue(issubclass(CustomerProjectProvisioningStep, Document))

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
