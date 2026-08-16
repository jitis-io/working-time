import sys
import types
import unittest
from contextlib import nullcontext
from unittest.mock import patch

if "frappe" not in sys.modules:
	from working_time.test_platform_operations import _bootstrap_frappe_stub

	_bootstrap_frappe_stub()

if "frappe.translate" not in sys.modules:
	frappe_translate = types.ModuleType("frappe.translate")
	frappe_translate.print_language = lambda language: nullcontext()
	sys.modules["frappe.translate"] = frappe_translate

frappe_utils = sys.modules.setdefault("frappe.utils", types.ModuleType("frappe.utils"))
frappe_utils_data = sys.modules.setdefault("frappe.utils.data", types.ModuleType("frappe.utils.data"))
if not hasattr(frappe_utils_data, "get_url"):
	frappe_utils_data.get_url = lambda path: path
frappe_utils.data = frappe_utils_data

from working_time.reminders import send_stale_reminders


class TestStaleReminders(unittest.TestCase):
	def test_multiple_stale_drafts_send_one_reminder_per_employee(self):
		settings = types.SimpleNamespace(send_reminders=True, submission_deadline_days=3)
		stale_entries = [
			("WT-0001", "EMP-0001"),
			("WT-0002", "EMP-0001"),
			("WT-0003", "EMP-0001"),
		]

		def get_value(doctype, name, fields):
			if doctype == "Employee":
				self.assertEqual(name, "EMP-0001")
				self.assertEqual(fields, ["user_id", "prefered_email", "first_name", "reports_to"])
				return "employee@example.com", "employee@example.com", "Erika", None
			if doctype == "User":
				self.assertEqual((name, fields), ("employee@example.com", "language"))
				return "de"
			raise AssertionError((doctype, name, fields))

		with (
			patch("working_time.reminders.frappe.get_single", return_value=settings),
			patch("working_time.reminders.frappe.get_all", return_value=stale_entries),
			patch("working_time.reminders.frappe.db.get_value", side_effect=get_value),
			patch("working_time.reminders.frappe.sendmail", create=True) as sendmail,
			patch("working_time.reminders.get_url", side_effect=lambda path: path),
			patch("working_time.reminders.print_language", side_effect=lambda language: nullcontext()),
		):
			send_stale_reminders()

		sendmail.assert_called_once()
		message = sendmail.call_args.kwargs["message"]
		self.assertIn("/app/working-time?employee=EMP-0001&docstatus=0", message)
		self.assertIn("older than 3 days", message)

	def test_stale_drafts_for_different_employees_send_separate_reminders(self):
		settings = types.SimpleNamespace(send_reminders=True, submission_deadline_days=3)
		stale_entries = [("WT-0001", "EMP-0001"), ("WT-0002", "EMP-0002")]

		def get_value(doctype, name, fields):
			if doctype == "Employee":
				return f"{name}@example.com", f"{name}@example.com", name, None
			if doctype == "User":
				return "en"
			raise AssertionError((doctype, name, fields))

		with (
			patch("working_time.reminders.frappe.get_single", return_value=settings),
			patch("working_time.reminders.frappe.get_all", return_value=stale_entries),
			patch("working_time.reminders.frappe.db.get_value", side_effect=get_value),
			patch("working_time.reminders.frappe.sendmail", create=True) as sendmail,
			patch("working_time.reminders.get_url", side_effect=lambda path: path),
			patch("working_time.reminders.print_language", side_effect=lambda language: nullcontext()),
		):
			send_stale_reminders()

		self.assertEqual(sendmail.call_count, 2)
