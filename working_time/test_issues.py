import sys
import types
import unittest
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from working_time.test_platform_operations import _bootstrap_frappe_stub

_bootstrap_frappe_stub()

import frappe

frappe_utils = sys.modules.setdefault("frappe.utils", types.ModuleType("frappe.utils"))
frappe_utils.cint = getattr(frappe_utils, "cint", lambda value: int(value or 0))
frappe_utils.get_time = getattr(
	frappe_utils,
	"get_time",
	lambda value: value if isinstance(value, time) else time.fromisoformat(str(value)),
)
frappe_utils.getdate = getattr(
	frappe_utils,
	"getdate",
	lambda value=None: value if isinstance(value, date) else date.fromisoformat(str(value)[:10]),
)
frappe.has_permission = getattr(frappe, "has_permission", lambda *args, **kwargs: True)

from working_time.issues import (
	add_task_time,
	get_issue_time_context,
	get_task_time_context,
	validate_issue_booking,
)


class TestIssueBooking(unittest.TestCase):
	def test_quick_entry_is_duration_first(self):
		quick_entry = (Path(__file__).parent / "public" / "js" / "time_booking.js").read_text()

		self.assertIn('fieldname: "duration_minutes"', quick_entry)
		self.assertNotIn('fieldname: "start_time"', quick_entry)
		self.assertIn("working_time.issues.book_time", quick_entry)

	def test_direct_working_time_booking_requires_issue_read_permission(self):
		issue = SimpleNamespace(name="ISS-2026-00001", customer=None)

		with (
			patch("working_time.issues.require_time_booking_identity", return_value="Administrator"),
			patch("working_time.issues.frappe.get_doc", return_value=issue),
			patch("working_time.issues.frappe.has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			validate_issue_booking(issue.name, "PROJ-0001")

	def test_issue_time_can_be_captured_before_project_allocation(self):
		issue = SimpleNamespace(name="ISS-2026-00002", customer=None)

		with (
			patch("working_time.issues.require_time_booking_identity", return_value="Administrator"),
			patch("working_time.issues.frappe.get_doc", return_value=issue),
			patch("working_time.issues.frappe.has_permission", return_value=True),
		):
			validate_issue_booking(issue.name, None)

	def test_issue_context_does_not_autoselect_unreadable_task(self):
		issue = SimpleNamespace(name="ISS-2026-00003", customer="CUST-0001", project="PROJ-0001")
		project = SimpleNamespace(
			name="PROJ-0001",
			project_name="Customer project",
			customer="CUST-0001",
			project_type="External",
			time_billable=1,
		)
		with (
			patch(
				"working_time.issues._require_booking_access",
				return_value=("EMP-0001", issue),
			),
			patch("working_time.issues.frappe.get_doc", return_value=project),
			patch("working_time.issues.frappe.has_permission", return_value=True),
			patch("working_time.issues.validate_issue_booking"),
			patch(
				"working_time.issues.frappe.get_list",
				side_effect=frappe.PermissionError("not permitted"),
			) as get_list,
			patch(
				"working_time.issues.frappe.get_all",
				return_value=[SimpleNamespace(name="TASK-HIDDEN", project=project.name)],
			) as get_all,
		):
			context = get_issue_time_context(issue.name, "2026-08-17")

		self.assertIsNone(context["task"])
		get_list.assert_called_once_with(
			"Task",
			filters={"issue": issue.name, "status": ("not in", ("Completed", "Cancelled"))},
			fields=["name", "project"],
			limit_page_length=2,
		)
		get_all.assert_not_called()

	def test_standalone_task_time_context_uses_task_project(self):
		task = SimpleNamespace(name="TASK-0001", project="PROJ-0001", issue=None)
		project = SimpleNamespace(
			name="PROJ-0001",
			customer=None,
			project_type="Internal",
			time_billable=0,
		)
		with (
			patch("working_time.issues._require_task_booking_access", return_value=("EMP-0001", task)),
			patch("working_time.issues.frappe.get_doc", return_value=project),
			patch("working_time.issues.frappe.has_permission", return_value=True),
		):
			context = get_task_time_context(task.name, "2026-08-17")

		self.assertEqual(context["task"], task.name)
		self.assertEqual(context["project"], project.name)
		self.assertEqual(context["billable"], 0)

	def test_cancelled_task_rejects_direct_time_booking_context(self):
		task = SimpleNamespace(name="TASK-CANCELLED", project="PROJ-0001", issue=None, status="Cancelled")
		with (
			patch("working_time.issues.require_time_booking_identity", return_value="Administrator"),
			patch("working_time.issues.get_user_employee", return_value="EMP-0001"),
			patch("working_time.issues.frappe.get_doc", return_value=task),
			patch("working_time.issues.frappe.has_permission", return_value=True),
			self.assertRaises(frappe.ValidationError),
		):
			get_task_time_context(task.name, "2026-08-17")

	def test_task_booking_appends_time_to_the_linked_task(self):
		task = SimpleNamespace(name="TASK-0001", project="PROJ-0001", issue=None)
		with (
			patch("working_time.issues._require_task_booking_access", return_value=("EMP-0001", task)),
			patch(
				"working_time.issues.get_task_time_context",
				return_value={"project": "PROJ-0001"},
			),
			patch(
				"working_time.issues._append_time_log",
				return_value={"working_time": "WT-0001", "route": "/app/working-time/WT-0001"},
			) as append,
		):
			result = add_task_time(task.name, "2026-08-17", 30, billable=0)

		append.assert_called_once_with(
			employee="EMP-0001",
			date="2026-08-17",
			duration_minutes=30,
			project="PROJ-0001",
			task=task.name,
			issue=None,
			start_time=None,
			customer_description=None,
			internal_note=None,
			billable=0,
		)
		self.assertEqual(result["working_time"], "WT-0001")
