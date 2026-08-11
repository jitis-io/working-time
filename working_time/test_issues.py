import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from working_time.issues import validate_issue_booking


class TestIssueBooking(unittest.TestCase):
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
