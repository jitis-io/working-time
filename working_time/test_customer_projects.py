import inspect
import types
import unittest
from unittest.mock import call, patch

from working_time.test_platform_operations import _bootstrap_frappe_stub

_bootstrap_frappe_stub()

import frappe

frappe.has_permission = getattr(frappe, "has_permission", lambda *args, **kwargs: True)
frappe.db.get_single_value = getattr(frappe.db, "get_single_value", lambda *args, **kwargs: None)

from working_time.customer_projects import (
	_ensure_customer_project,
	_preflight_project_name_conflicts,
	after_customer_insert,
	apply_invoice_project,
	assign_customer_project_to_issue,
	backfill_customer_projects,
	backfill_issue_projects,
	ensure_customer_project,
	sync_project_time_billing,
)
from working_time.hooks import doc_events

FrappeValidationError = getattr(frappe, "ValidationError", RuntimeError)


class FakeDocument(types.SimpleNamespace):
	def get(self, key, default=None):
		return getattr(self, key, default)

	def insert(self, **kwargs):
		self.insert_kwargs = kwargs
		return self

	def save(self, **kwargs):
		self.save_kwargs = kwargs
		return self


class TestCustomerProjects(unittest.TestCase):
	def test_whitelisted_api_exposes_no_permission_bypass_argument(self):
		self.assertEqual(list(inspect.signature(ensure_customer_project).parameters), ["customer"])

	def test_linked_customer_project_is_reused_under_customer_row_lock(self):
		customer = FakeDocument(name="CUST-0001", customer_project="PROJ-0001")
		project = FakeDocument(
			name="PROJ-0001",
			project_name="Legacy descriptive name",
			customer=customer.name,
			status="Open",
			is_active="Yes",
		)

		def get_doc(doctype, name=None):
			return customer if doctype == "Customer" else project

		with (
			patch("working_time.customer_projects.frappe.db.sql") as sql,
			patch("working_time.customer_projects.frappe.get_doc", side_effect=get_doc),
			patch("working_time.customer_projects.frappe.db.get_value", return_value=project.name),
			patch("working_time.customer_projects.frappe.db.set_value") as set_value,
		):
			result = _ensure_customer_project(customer.name, ignore_permissions=True)

		sql.assert_called_once_with(
			"select name from `tabCustomer` where name=%s for update",
			(customer.name,),
		)
		set_value.assert_not_called()
		self.assertFalse(hasattr(project, "save_kwargs"))
		self.assertEqual(result, {"project": project.name, "created": False, "reopened": False})

	def test_exact_customer_number_project_is_linked_reopened_and_then_reused(self):
		customer = FakeDocument(name="CUST-0002", customer_project=None)
		project = FakeDocument(
			name="PROJ-0002",
			project_name=customer.name,
			customer=customer.name,
			status="Completed",
			is_active="No",
		)

		def get_doc(doctype, name=None):
			return customer if doctype == "Customer" else project

		def get_value(doctype, filters, fieldname):
			if doctype != "Project" or fieldname != "name":
				raise AssertionError((doctype, filters, fieldname))
			if "name" in filters:
				return project.name if filters == {"name": project.name, "customer": customer.name} else None
			self.assertEqual(
				filters,
				{"project_name": customer.name, "customer": customer.name},
			)
			return project.name

		with (
			patch("working_time.customer_projects.frappe.db.sql"),
			patch("working_time.customer_projects.frappe.get_doc", side_effect=get_doc),
			patch("working_time.customer_projects.frappe.db.get_value", side_effect=get_value),
			patch("working_time.customer_projects.frappe.db.set_value") as set_value,
		):
			first = _ensure_customer_project(customer.name, ignore_permissions=True)
			second = _ensure_customer_project(customer.name, ignore_permissions=True)

		self.assertEqual(first, {"project": project.name, "created": False, "reopened": True})
		self.assertEqual(second, {"project": project.name, "created": False, "reopened": False})
		self.assertEqual(project.status, "Open")
		self.assertEqual(project.is_active, "Yes")
		self.assertFalse(hasattr(project, "save_kwargs"))
		self.assertEqual(
			set_value.call_args_list,
			[
				call("Project", project.name, {"status": "Open", "is_active": "Yes"}),
				call(
					"Customer",
					customer.name,
					"customer_project",
					project.name,
					update_modified=False,
				),
			],
		)

	def test_completed_task_based_project_is_normalized_as_permanent_customer_account(self):
		customer = FakeDocument(name="CUST-PERMANENT", customer_project="PROJ-PERMANENT")
		project = FakeDocument(
			name="PROJ-PERMANENT",
			project_name=customer.name,
			customer=customer.name,
			status="Completed",
			is_active="Yes",
			percent_complete_method="Task Completion",
			percent_complete=100,
		)

		def get_doc(doctype, name=None):
			return customer if doctype == "Customer" else project

		with (
			patch("working_time.customer_projects.frappe.db.sql"),
			patch("working_time.customer_projects.frappe.get_doc", side_effect=get_doc),
			patch("working_time.customer_projects.frappe.db.get_value", return_value=project.name),
			patch("working_time.customer_projects.frappe.db.set_value") as set_value,
		):
			first = _ensure_customer_project(customer.name, ignore_permissions=True)
			second = _ensure_customer_project(customer.name, ignore_permissions=True)

		self.assertEqual(first, {"project": project.name, "created": False, "reopened": True})
		self.assertEqual(second, {"project": project.name, "created": False, "reopened": False})
		self.assertEqual(project.status, "Open")
		self.assertEqual(project.is_active, "Yes")
		self.assertEqual(project.percent_complete_method, "Manual")
		self.assertEqual(project.percent_complete, 0)
		set_value.assert_called_once_with(
			"Project",
			project.name,
			{
				"status": "Open",
				"percent_complete_method": "Manual",
				"percent_complete": 0,
			},
		)

	def test_unrelated_project_is_not_adopted_when_creating_customer_project(self):
		customer = FakeDocument(name="CUST-0003", customer_project="PROJ-OTHER")
		new_project = FakeDocument(name="PROJ-0003")

		def get_doc(doctype, name=None):
			if doctype == "Customer":
				return customer
			if isinstance(doctype, dict):
				new_project.values = doctype
				return new_project
			raise AssertionError((doctype, name))

		with (
			patch("working_time.customer_projects.frappe.db.sql"),
			patch("working_time.customer_projects.frappe.get_doc", side_effect=get_doc),
			patch("working_time.customer_projects.frappe.db.get_value", return_value=None) as get_value,
			patch("working_time.customer_projects._default_company", return_value="JITIS GmbH"),
			patch("working_time.customer_projects.frappe.db.set_value") as set_value,
			patch("working_time.customer_projects.frappe.has_permission") as has_permission,
		):
			result = _ensure_customer_project(customer.name, ignore_permissions=True)

		self.assertEqual(
			get_value.call_args_list,
			[
				call(
					"Project",
					{"name": "PROJ-OTHER", "customer": customer.name},
					"name",
				),
				call(
					"Project",
					{"project_name": customer.name, "customer": customer.name},
					"name",
				),
				call(
					"Project",
					{"project_name": customer.name},
					["name", "customer"],
					as_dict=True,
				),
			],
		)
		self.assertEqual(
			new_project.values,
			{
				"doctype": "Project",
				"project_name": customer.name,
				"company": "JITIS GmbH",
				"customer": customer.name,
				"status": "Open",
				"is_active": "Yes",
				"percent_complete_method": "Manual",
				"percent_complete": 0,
				"time_billable": 0,
				"billing_model": "Non-billable",
			},
		)
		self.assertEqual(new_project.insert_kwargs, {"ignore_permissions": True})
		self.assertEqual(result, {"project": new_project.name, "created": True, "reopened": False})
		set_value.assert_called_once()
		has_permission.assert_not_called()

	def test_conflicting_visible_project_name_is_reported_without_adoption(self):
		customer = FakeDocument(name="CUST-0008", customer_project=None)
		conflict = FakeDocument(name="PROJ-OTHER", customer="CUST-OTHER")

		def get_value(doctype, filters, fieldname, **kwargs):
			if filters == {"project_name": customer.name, "customer": customer.name}:
				return None
			if filters == {"project_name": customer.name}:
				self.assertEqual(kwargs, {"as_dict": True})
				return conflict
			raise AssertionError((doctype, filters, fieldname, kwargs))

		with (
			patch("working_time.customer_projects.frappe.db.sql"),
			patch("working_time.customer_projects.frappe.get_doc", return_value=customer),
			patch("working_time.customer_projects.frappe.db.get_value", side_effect=get_value),
			patch("working_time.customer_projects.frappe.db.set_value") as set_value,
			self.assertRaises(FrappeValidationError),
		):
			_ensure_customer_project(customer.name, ignore_permissions=True)

		set_value.assert_not_called()

	def test_cancelled_exact_project_is_not_silently_reactivated(self):
		customer = FakeDocument(name="CUST-0004", customer_project=None)
		project = FakeDocument(
			name="PROJ-CANCELLED",
			project_name=customer.name,
			customer=customer.name,
			status="Cancelled",
			is_active="No",
		)

		def get_doc(doctype, name=None):
			return customer if doctype == "Customer" else project

		with (
			patch("working_time.customer_projects.frappe.db.sql"),
			patch("working_time.customer_projects.frappe.get_doc", side_effect=get_doc),
			patch("working_time.customer_projects.frappe.db.get_value", return_value=project.name),
			patch("working_time.customer_projects.frappe.db.set_value") as set_value,
			self.assertRaises(FrappeValidationError),
		):
			_ensure_customer_project(customer.name, ignore_permissions=True)

		set_value.assert_not_called()
		self.assertFalse(hasattr(project, "save_kwargs"))

	def test_whitelisted_api_always_enforces_customer_permissions(self):
		customer = FakeDocument(name="CUST-0005", customer_project="PROJ-0005")
		project = FakeDocument(
			name="PROJ-0005",
			customer=customer.name,
			status="Open",
			is_active="Yes",
		)

		def get_doc(doctype, name=None):
			return customer if doctype == "Customer" else project

		with (
			patch("working_time.customer_projects.frappe.db.sql"),
			patch("working_time.customer_projects.frappe.get_doc", side_effect=get_doc),
			patch("working_time.customer_projects.frappe.has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			ensure_customer_project(customer.name)

	def test_direct_call_checks_project_read_and_write_before_reopening(self):
		customer = FakeDocument(name="CUST-0006", customer_project="PROJ-0006")
		project = FakeDocument(
			name="PROJ-0006",
			customer=customer.name,
			status="On hold",
			is_active="No",
		)

		def get_doc(doctype, name=None):
			return customer if doctype == "Customer" else project

		with (
			patch("working_time.customer_projects.frappe.db.sql"),
			patch("working_time.customer_projects.frappe.get_doc", side_effect=get_doc),
			patch("working_time.customer_projects.frappe.db.get_value", return_value=project.name),
			patch("working_time.customer_projects.frappe.has_permission", return_value=True) as permission,
			patch("working_time.customer_projects.frappe.db.set_value"),
		):
			result = ensure_customer_project(customer.name)

		self.assertEqual(
			permission.call_args_list,
			[
				call("Customer", "read", doc=customer),
				call("Customer", "write", doc=customer),
				call("Project", "read", doc=project),
				call("Project", "write", doc=project),
			],
		)
		self.assertEqual(project.status, "Open")
		self.assertEqual(project.is_active, "Yes")
		self.assertTrue(result["reopened"])

	def test_missing_default_company_fails_before_project_or_mapping_creation(self):
		customer = FakeDocument(name="CUST-0007", customer_project=None)

		with (
			patch("working_time.customer_projects.frappe.db.sql"),
			patch("working_time.customer_projects.frappe.get_doc", return_value=customer) as get_doc,
			patch("working_time.customer_projects.frappe.db.get_value", return_value=None),
			patch("working_time.customer_projects._default_company", return_value=None),
			patch("working_time.customer_projects.frappe.db.set_value") as set_value,
			self.assertRaises(FrappeValidationError),
		):
			_ensure_customer_project(customer.name, ignore_permissions=True)

		self.assertEqual(get_doc.call_args_list, [call("Customer", customer.name)])
		set_value.assert_not_called()

	def test_backfill_skips_before_querying_customers_without_default_company(self):
		with (
			patch("working_time.customer_projects._default_company", return_value=None),
			patch("working_time.customer_projects.frappe.get_all") as get_all,
			patch("working_time.customer_projects._ensure_customer_project") as ensure,
		):
			result = backfill_customer_projects()

		self.assertEqual(result, {"processed": 0, "created": 0, "reopened": 0, "skipped": True})
		get_all.assert_not_called()
		ensure.assert_not_called()

	def test_backfill_processes_only_enabled_customers(self):
		results = [
			{"project": "PROJ-1", "created": True, "reopened": False},
			{"project": "PROJ-2", "created": False, "reopened": True},
		]
		with (
			patch("working_time.customer_projects._default_company", return_value="JITIS GmbH"),
			patch(
				"working_time.customer_projects.frappe.get_all",
				return_value=["CUST-1", "CUST-2"],
			) as get_all,
			patch(
				"working_time.customer_projects._ensure_customer_project",
				side_effect=results,
			) as ensure,
			patch("working_time.customer_projects._preflight_project_name_conflicts") as preflight,
		):
			result = backfill_customer_projects()

		get_all.assert_called_once_with(
			"Customer",
			filters={"disabled": 0},
			pluck="name",
			order_by="name asc",
			limit_page_length=0,
		)
		self.assertEqual(
			ensure.call_args_list,
			[
				call("CUST-1", ignore_permissions=True),
				call("CUST-2", ignore_permissions=True),
			],
		)
		preflight.assert_called_once_with(["CUST-1", "CUST-2"])
		self.assertEqual(result, {"processed": 2, "created": 1, "reopened": 1, "skipped": False})

	def test_backfill_conflict_preflight_aborts_before_first_customer_write(self):
		with (
			patch("working_time.customer_projects._default_company", return_value="JITIS GmbH"),
			patch("working_time.customer_projects.frappe.get_all", return_value=["CUST-1", "CUST-2"]),
			patch(
				"working_time.customer_projects._preflight_project_name_conflicts",
				side_effect=FrappeValidationError("conflict"),
			),
			patch("working_time.customer_projects._ensure_customer_project") as ensure,
			self.assertRaises(FrappeValidationError),
		):
			backfill_customer_projects()

		ensure.assert_not_called()

	def test_preflight_ignores_unrelated_name_conflict_when_valid_link_is_reusable(self):
		customer = FakeDocument(name="CUST-1", customer_project="PROJ-LINKED")
		project = FakeDocument(name="PROJ-LINKED", customer=customer.name, status="Open")

		with (
			patch("working_time.customer_projects.frappe.get_doc", return_value=customer),
			patch("working_time.customer_projects._load_linked_project", return_value=project),
			patch("working_time.customer_projects._load_exact_customer_project") as load_exact,
			patch("working_time.customer_projects._project_name_conflict") as conflict,
		):
			_preflight_project_name_conflicts([customer.name])

		load_exact.assert_not_called()
		conflict.assert_not_called()

	def test_issue_backfill_uses_only_customer_mapping_for_open_unmapped_issues(self):
		issues = [
			FakeDocument(name="ISS-0001", customer="CUST-1"),
			FakeDocument(name="ISS-0002", customer="CUST-2"),
		]

		def get_value(doctype, name, fieldname):
			self.assertEqual((doctype, fieldname), ("Customer", "customer_project"))
			return "PROJ-1" if name == "CUST-1" else None

		with (
			patch("working_time.customer_projects.frappe.get_all", return_value=issues) as get_all,
			patch(
				"working_time.customer_projects.frappe.db.get_value", side_effect=get_value
			) as get_value_mock,
			patch("working_time.customer_projects.frappe.db.set_value") as set_value,
		):
			result = backfill_issue_projects()

		get_all.assert_called_once_with(
			"Issue",
			filters={
				"status": ("not in", ("Resolved", "Closed")),
				"customer": ("is", "set"),
				"project": ("is", "not set"),
			},
			fields=["name", "customer"],
			order_by="name asc",
			limit_page_length=0,
		)
		self.assertEqual(get_value_mock.call_count, 2)
		set_value.assert_called_once_with(
			"Issue",
			"ISS-0001",
			"project",
			"PROJ-1",
			update_modified=False,
		)
		self.assertEqual(result, {"matched": 2, "updated": 1, "skipped": 1})

	def test_issue_backfill_is_idempotent_after_issue_has_been_mapped(self):
		with (
			patch(
				"working_time.customer_projects.frappe.get_all",
				side_effect=[[FakeDocument(name="ISS-0001", customer="CUST-1")], []],
			),
			patch(
				"working_time.customer_projects.frappe.db.get_value",
				return_value="PROJ-1",
			),
			patch("working_time.customer_projects.frappe.db.set_value") as set_value,
		):
			first = backfill_issue_projects()
			second = backfill_issue_projects()

		self.assertEqual(first["updated"], 1)
		self.assertEqual(second["updated"], 0)
		self.assertEqual(set_value.call_count, 1)

	def test_customer_insert_provisions_only_enabled_customer(self):
		with patch(
			"working_time.customer_projects._ensure_customer_project",
			return_value={"project": "PROJ-1", "created": True, "reopened": False},
		) as ensure:
			self.assertIsNone(after_customer_insert(FakeDocument(name="CUST-OFF", disabled=1)))
			self.assertIsNone(after_customer_insert(FakeDocument(name="CUST-ON", disabled=0)))

		ensure.assert_called_once_with("CUST-ON", ignore_permissions=True)

	def test_issue_without_project_uses_customer_mapping(self):
		issue = FakeDocument(customer="CUST-0001", project=None)

		def get_value(doctype, name, fieldname):
			if doctype == "Customer":
				return "PROJ-0001"
			if doctype == "Project":
				return "CUST-0001"
			raise AssertionError((doctype, name, fieldname))

		with patch("working_time.customer_projects.frappe.db.get_value", side_effect=get_value):
			assign_customer_project_to_issue(issue)

		self.assertEqual(issue.project, "PROJ-0001")

	def test_issue_rejects_existing_customer_project_mismatch(self):
		issue = FakeDocument(customer="CUST-0001", project="PROJ-OTHER")
		with (
			patch("working_time.customer_projects.frappe.db.get_value", return_value="CUST-OTHER"),
			self.assertRaises(FrappeValidationError),
		):
			assign_customer_project_to_issue(issue)

	def test_invoice_header_only_fills_empty_item_projects(self):
		invoice = FakeDocument(
			project="PROJ-HEADER",
			items=[
				FakeDocument(project=None),
				FakeDocument(project=""),
				FakeDocument(project="PROJ-EXPLICIT"),
			],
		)

		apply_invoice_project(invoice)

		self.assertEqual(
			[item.project for item in invoice.items],
			["PROJ-HEADER", "PROJ-HEADER", "PROJ-EXPLICIT"],
		)

	def test_invoice_project_validation_hook_covers_purchase_and_sales_invoice(self):
		for doctype in ("Purchase Invoice", "Sales Invoice"):
			with self.subTest(doctype=doctype):
				self.assertEqual(
					doc_events[doctype]["validate"],
					"working_time.customer_projects.apply_invoice_project",
				)

	def test_simple_time_billing_switch_keeps_legacy_model_compatible(self):
		billable = FakeDocument(time_billable=1, billing_model="Recurring")
		non_billable = FakeDocument(time_billable=0, billing_model="Time and Material")
		fixed = FakeDocument(time_billable=0, billing_model="Fixed Price")

		sync_project_time_billing(billable)
		sync_project_time_billing(non_billable)
		sync_project_time_billing(fixed)

		self.assertEqual(billable.billing_model, "Time and Material")
		self.assertEqual(non_billable.billing_model, "Non-billable")
		self.assertEqual(fixed.billing_model, "Fixed Price")


if __name__ == "__main__":
	unittest.main()
