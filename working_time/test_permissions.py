import sys
import types
import unittest
from unittest.mock import patch

if "frappe" not in sys.modules:
	from working_time.test_platform_operations import _bootstrap_frappe_stub

	_bootstrap_frappe_stub()

import frappe


class FakeAggregate:
	def __init__(self, field):
		self.field = field

	def as_(self, alias):
		self.alias = alias
		return self


class FakeField:
	def __init__(self, name):
		self.name = name

	def __eq__(self, value):
		return ("eq", self.name, value)

	def __ge__(self, value):
		return ("ge", self.name, value)

	def __le__(self, value):
		return ("le", self.name, value)


class FakeTable:
	def __getattr__(self, name):
		return FakeField(name)

	def __getitem__(self, name):
		return FakeField(name)


class FakeQuery:
	def __init__(self):
		self.conditions = []

	def select(self, *args):
		return self

	def where(self, condition):
		self.conditions.append(condition)
		return self

	def groupby(self, *args):
		return self

	def run(self, **kwargs):
		return []


class FakeQueryBuilder:
	def __init__(self):
		self.query = FakeQuery()

	def DocType(self, name):
		return FakeTable()

	def from_(self, table):
		return self.query


if "frappe.query_builder.functions" not in sys.modules:
	query_builder = types.ModuleType("frappe.query_builder")
	query_builder_functions = types.ModuleType("frappe.query_builder.functions")
	query_builder_functions.Sum = FakeAggregate
	sys.modules["frappe.query_builder"] = query_builder
	sys.modules["frappe.query_builder.functions"] = query_builder_functions

if "frappe.utils.data" not in sys.modules:
	frappe_utils = types.ModuleType("frappe.utils")
	frappe_utils_data = types.ModuleType("frappe.utils.data")
	frappe_utils_data.getdate = lambda value=None: value
	sys.modules["frappe.utils"] = frappe_utils
	sys.modules["frappe.utils.data"] = frappe_utils_data

try:
	import babel.dates
except ModuleNotFoundError:
	babel = types.ModuleType("babel")
	babel_dates = types.ModuleType("babel.dates")
	babel_dates.format_date = lambda value, **kwargs: str(value)
	sys.modules["babel"] = babel
	sys.modules["babel.dates"] = babel_dates

from working_time.hooks import has_permission, permission_query_conditions
from working_time.permissions import (
	TECHNICAL_SERVICE_ROLES,
	require_employee_access,
	working_time_has_permission,
	working_time_query_conditions,
)
from working_time.working_time.report.expected_and_actual_working_time import (
	expected_and_actual_working_time,
)
from working_time.working_time.report.working_time_summary import working_time_summary


class FakeDocument(types.SimpleNamespace):
	def get(self, key, default=None):
		return getattr(self, key, default)


class TestWorkingTimePermissions(unittest.TestCase):
	def test_hooks_register_both_working_time_permission_layers(self):
		self.assertEqual(
			permission_query_conditions["Working Time"],
			"working_time.permissions.working_time_query_conditions",
		)
		self.assertEqual(
			has_permission["Working Time"],
			"working_time.permissions.working_time_has_permission",
		)

	def test_system_manager_query_is_unrestricted(self):
		with patch("working_time.permissions.frappe.get_roles", return_value=["System Manager"]):
			self.assertEqual(working_time_query_conditions("manager@example.com"), "")

	def test_employee_query_is_restricted_to_linked_employee(self):
		with (
			patch("working_time.permissions.frappe.get_roles", return_value=["Employee"]),
			patch("working_time.permissions.get_user_employee", return_value="EMP-0001"),
			patch("working_time.permissions.frappe.db.escape", return_value="'EMP-0001'"),
		):
			condition = working_time_query_conditions("employee@example.com")

		self.assertEqual(condition, "`tabWorking Time`.`employee` = 'EMP-0001'")

	def test_employee_without_mapping_gets_empty_query_scope(self):
		with (
			patch("working_time.permissions.frappe.get_roles", return_value=["Employee"]),
			patch("working_time.permissions.get_user_employee", return_value=None),
		):
			self.assertEqual(working_time_query_conditions("unmapped@example.com"), "1=0")

	def test_employee_document_operations_are_limited_to_own_employee(self):
		own = FakeDocument(employee="EMP-0001")
		other = FakeDocument(employee="EMP-0002")
		permission_types = ("read", "create", "write", "submit", "cancel", "delete", "amend")
		with (
			patch("working_time.permissions.frappe.get_roles", return_value=["Employee"]),
			patch("working_time.permissions.get_user_employee", return_value="EMP-0001"),
		):
			for permission_type in permission_types:
				with self.subTest(permission_type=permission_type):
					self.assertTrue(working_time_has_permission(own, permission_type, "employee@example.com"))
					self.assertFalse(
						working_time_has_permission(other, permission_type, "employee@example.com")
					)

	def test_create_without_own_employee_is_denied(self):
		with (
			patch("working_time.permissions.frappe.get_roles", return_value=["Employee"]),
			patch("working_time.permissions.get_user_employee", return_value="EMP-0001"),
		):
			self.assertFalse(
				working_time_has_permission(FakeDocument(employee=None), "create", "employee@example.com")
			)

	def test_employee_without_mapping_has_no_document_access(self):
		with (
			patch("working_time.permissions.frappe.get_roles", return_value=["Employee"]),
			patch("working_time.permissions.get_user_employee", return_value=None),
		):
			self.assertFalse(
				working_time_has_permission(FakeDocument(employee="EMP-0001"), "read", "unmapped@example.com")
			)

	def test_system_manager_has_document_access_without_employee_mapping(self):
		with patch("working_time.permissions.frappe.get_roles", return_value=["System Manager"]):
			self.assertTrue(
				working_time_has_permission(
					FakeDocument(employee="EMP-9999"), "delete", "manager@example.com"
				)
			)

	def test_website_user_is_explicitly_denied(self):
		with (
			patch("working_time.permissions.frappe.db.get_value", return_value="Website User"),
			patch("working_time.permissions.frappe.get_roles", return_value=["System Manager"]),
		):
			self.assertEqual(working_time_query_conditions("portal@example.com"), "1=0")
			self.assertFalse(
				working_time_has_permission(FakeDocument(employee="EMP-0001"), "write", "portal@example.com")
			)
			with self.assertRaises(frappe.PermissionError):
				require_employee_access("EMP-0001", "portal@example.com")

	def test_technical_service_roles_are_explicitly_denied(self):
		for service_role in TECHNICAL_SERVICE_ROLES:
			with (
				self.subTest(service_role=service_role),
				patch("working_time.permissions.frappe.db.get_value", return_value="System User"),
				patch(
					"working_time.permissions.frappe.get_roles",
					return_value=["System Manager", service_role],
				),
			):
				self.assertEqual(working_time_query_conditions("service@example.com"), "1=0")
				self.assertFalse(
					working_time_has_permission(
						FakeDocument(employee="EMP-0001"), "write", "service@example.com"
					)
				)
				with self.assertRaises(frappe.PermissionError):
					require_employee_access("EMP-0001", "service@example.com")

	def test_employee_scope_accepts_own_employee_and_rejects_another(self):
		with (
			patch("working_time.permissions.frappe.get_roles", return_value=["Employee"]),
			patch("working_time.permissions.get_user_employee", return_value="EMP-0001"),
		):
			self.assertEqual(
				require_employee_access("EMP-0001", "employee@example.com"),
				"EMP-0001",
			)
			with self.assertRaises(frappe.PermissionError):
				require_employee_access("EMP-0002", "employee@example.com")

	def test_employee_scope_rejects_user_without_employee_mapping(self):
		with (
			patch("working_time.permissions.frappe.get_roles", return_value=["Employee"]),
			patch("working_time.permissions.get_user_employee", return_value=None),
			self.assertRaises(frappe.PermissionError),
		):
			require_employee_access(user="unmapped@example.com")

	def test_summary_direct_query_adds_employee_scope(self):
		query_builder = FakeQueryBuilder()
		with (
			patch.object(working_time_summary.frappe, "qb", query_builder, create=True),
			patch.object(working_time_summary, "Sum", FakeAggregate),
			patch.object(working_time_summary, "require_employee_access", return_value="EMP-0001"),
		):
			working_time_summary.execute({"from_date": "2026-08-01", "to_date": "2026-08-31"})

		self.assertIn(("eq", "employee", "EMP-0001"), query_builder.query.conditions)

	def test_expected_actual_direct_query_denies_unmapped_employee(self):
		with (
			patch.object(
				expected_and_actual_working_time,
				"require_employee_access",
				side_effect=frappe.PermissionError,
			),
			self.assertRaises(frappe.PermissionError),
		):
			list(
				expected_and_actual_working_time.get_data(
					"EMP-0001", "2026-08-01", "2026-08-01", 8, "working_time"
				)
			)
