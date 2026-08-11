import json
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from working_time.test_platform_operations import FakeDocument, _bootstrap_frappe_stub

_bootstrap_frappe_stub()

import frappe

frappe_utils = sys.modules.setdefault("frappe.utils", types.ModuleType("frappe.utils"))
frappe_utils.cint = getattr(frappe_utils, "cint", lambda value: int(value or 0))
frappe_utils.flt = getattr(frappe_utils, "flt", lambda value: float(value or 0))
frappe_utils.getdate = getattr(
	frappe_utils,
	"getdate",
	lambda value=None: value if isinstance(value, date) else date.fromisoformat(str(value)[:10]),
)
frappe_utils.nowdate = getattr(frappe_utils, "nowdate", lambda: "2026-08-11")

frappe.has_permission = getattr(frappe, "has_permission", lambda *args, **kwargs: True)
frappe.get_list = getattr(frappe, "get_list", lambda *args, **kwargs: [])
frappe.get_hooks = getattr(frappe, "get_hooks", lambda *args, **kwargs: [])
frappe.get_attr = getattr(frappe, "get_attr", lambda *args, **kwargs: None)
frappe.get_traceback = getattr(frappe, "get_traceback", lambda: "traceback")
frappe.log_error = getattr(frappe, "log_error", lambda *args, **kwargs: None)
frappe.session = getattr(frappe, "session", FakeDocument(user="test@example.com"))

from working_time.hooks import working_time_custom_fields
from working_time.work_cockpit import (
	_apply_time_and_billing_context,
	_assigned_filters,
	_filter_view,
	_get_external_items,
	_normalize_external_item,
	_permission_aware_list,
	get_issue_attachments,
	promote_issue_to_task,
)


def item(**values):
	return {
		"source": "erpnext",
		"item_type": "Task",
		"name": "TASK-1",
		"title": "Task",
		"status": "Open",
		"due_date": None,
		"operational_state": "Normal",
		"actual_hours": 0,
		"worked_today": False,
		"billing_statuses": [],
		"unbilled": False,
		"commercial_context": {"sales_invoices": []},
		**values,
	}


class TestWorkCockpit(unittest.TestCase):
	def test_v15_custom_fields_keep_operational_state_separate_from_native_status(self):
		issue_fields = {field["fieldname"]: field for field in working_time_custom_fields["Issue"]}
		task_fields = {field["fieldname"]: field for field in working_time_custom_fields["Task"]}
		project_fields = {field["fieldname"]: field for field in working_time_custom_fields["Project"]}

		self.assertEqual(
			issue_fields["working_time_operational_state"]["options"].splitlines(),
			["Normal", "Blockiert", "Wartet auf Kunde"],
		)
		self.assertEqual(
			task_fields["working_time_operational_state"]["options"].splitlines(),
			["Normal", "Blockiert", "Wartet auf Kunde"],
		)
		self.assertEqual(issue_fields["working_time_planned_date"]["fieldtype"], "Date")
		self.assertEqual(project_fields["contract"]["options"], "Contract")

	def test_work_cockpit_page_and_workspace_link_have_stable_names(self):
		module = Path(__file__).parent / "working_time"
		page = json.loads((module / "page" / "work_cockpit" / "work_cockpit.json").read_text())
		workspace = json.loads(
			(module / "workspace" / "platform_operations" / "platform_operations.json").read_text()
		)

		self.assertEqual(page["name"], "work-cockpit")
		self.assertIn(
			{
				"hidden": 0,
				"is_query_report": 0,
				"label": "Work Cockpit",
				"link_count": 0,
				"link_to": "work-cockpit",
				"link_type": "Page",
				"onboard": 0,
				"type": "Link",
			},
			workspace["links"],
		)

	def test_permission_aware_subquery_fails_closed_without_breaking_other_sources(self):
		with patch(
			"working_time.work_cockpit.frappe.get_list",
			side_effect=frappe.PermissionError("denied"),
		):
			self.assertEqual(_permission_aware_list("Issue", fields=["name"]), [])

	def test_non_manager_query_requires_exact_current_user_assignment(self):
		with patch("working_time.work_cockpit.is_system_manager", return_value=False):
			filters = _assigned_filters(("Open", "Working"), "dev@example.com")

		self.assertEqual(filters["status"], ["in", ["Open", "Working"]])
		self.assertEqual(filters["_assign"], ["like", '%"dev@example.com"%'])

	def test_assignment_filter_escapes_like_wildcards_in_user_id(self):
		with patch("working_time.work_cockpit.is_system_manager", return_value=False):
			filters = _assigned_filters(("Open",), "dev_one%two@example.com")

		self.assertEqual(filters["_assign"], ["like", '%"dev\\_one\\%two@example.com"%'])

	def test_system_manager_query_still_uses_native_permission_aware_list_without_assignment_filter(self):
		with patch("working_time.work_cockpit.is_system_manager", return_value=True):
			filters = _assigned_filters(("Open",), "manager@example.com")

		self.assertEqual(filters, {"status": ["in", ["Open"]]})

	def test_views_use_independent_operational_state_and_exact_unbilled_flag(self):
		blocked = item(name="TASK-B", operational_state="Blockiert")
		waiting = item(name="TASK-W", operational_state="Wartet auf Kunde")
		unbilled = item(name="TASK-U", unbilled=True, billing_statuses=["Eligible"])

		self.assertEqual(_filter_view([blocked, waiting, unbilled], "blocked"), [blocked])
		self.assertEqual(_filter_view([blocked, waiting, unbilled], "waiting_customer"), [waiting])
		self.assertEqual(_filter_view([blocked, waiting, unbilled], "unbilled"), [unbilled])

	def test_today_contains_due_work_and_worked_today(self):
		due = item(name="TASK-D", due_date="2026-08-11")
		future = item(name="TASK-F", due_date="2026-08-12")
		worked = item(name="TASK-T", due_date="2026-08-12", worked_today=True)

		with patch("working_time.work_cockpit.nowdate", return_value="2026-08-11"):
			self.assertEqual(_filter_view([due, future, worked], "today"), [due, worked])

	def test_provider_failure_isolated_from_healthy_provider(self):
		def healthy(**kwargs):
			return [{"external_id": "GH-1", "title": "GitHub issue"}]

		def broken(**kwargs):
			raise RuntimeError("unavailable")

		with (
			patch("working_time.work_cockpit._provider_functions", return_value=[healthy, broken]),
			patch("working_time.work_cockpit.frappe.log_error") as log_error,
		):
			items, errors = _get_external_items("all", "dev@example.com")

		self.assertEqual([row["name"] for row in items], ["GH-1"])
		self.assertEqual(errors, [f"{broken.__module__}.{broken.__name__}"])
		log_error.assert_called_once()

	def test_external_items_are_allowlisted_and_invalid_state_is_normalized(self):
		result = _normalize_external_item(
			{
				"external_id": "GH-2",
				"title": "Private issue",
				"operational_state": "Provider secret state",
				"unknown_secret": "must not leave provider boundary",
				"route": "javascript:alert(document.cookie)",
				"commercial_context": {
					"contract": "CON-1",
					"sales_invoices": ["SINV-1"],
					"api_token": "must not leave provider boundary",
				},
			},
			"github.provider",
		)

		self.assertEqual(result["operational_state"], "Normal")
		self.assertNotIn("unknown_secret", result)
		self.assertIsNone(result["route"])
		self.assertNotIn("api_token", result["commercial_context"])
		self.assertIsNone(_normalize_external_item({"title": "Missing ID"}, "github.provider"))
		blocked = _normalize_external_item(
			{"external_id": "GH-3", "title": "Blocked issue", "operational_state": "Blocked"},
			"github.provider",
		)
		self.assertEqual(blocked["operational_state"], "Blockiert")

	def test_billing_context_uses_existing_eligibility_status(self):
		work_item = item()
		detail = FakeDocument(
			name="TSD-1",
			parent="TS-1",
			project="PROJ-1",
			task="TASK-1",
			issue=None,
			hours=1.5,
			billing_hours=1.5,
			is_billable=1,
			from_time="2026-08-11 09:00:00",
			sales_invoice=None,
		)
		with (
			patch("working_time.work_cockpit._relevant_timesheet_details", return_value=[detail]),
			patch("working_time.work_cockpit._claimed_billing_sources", return_value={}),
			patch("working_time.work_cockpit._billing_status", return_value=("Eligible", {})) as status,
			patch("working_time.work_cockpit._review_invoice_links", return_value={"TSD-1": set()}),
			patch("working_time.work_cockpit._visible_links", return_value=set()),
			patch("working_time.work_cockpit.nowdate", return_value="2026-08-11"),
		):
			_apply_time_and_billing_context([work_item])

		status.assert_called_once()
		self.assertEqual(work_item["actual_hours"], 1.5)
		self.assertEqual(work_item["billing_statuses"], ["Eligible"])
		self.assertTrue(work_item["unbilled"])
		self.assertTrue(work_item["worked_today"])

	def test_existing_open_task_is_reused_after_issue_row_lock(self):
		issue = FakeDocument(name="ISS-1")
		task = FakeDocument(name="TASK-1")

		def locked_query(query, *args, **kwargs):
			if "from `tabTask`" in query:
				return [FakeDocument(name="TASK-1")]
			return []

		with (
			patch("working_time.work_cockpit.require_time_booking_identity", return_value="dev@example.com"),
			patch("working_time.work_cockpit.frappe.has_permission", return_value=True),
			patch("working_time.work_cockpit.frappe.db.sql", create=True, side_effect=locked_query) as sql,
			patch("working_time.work_cockpit._issue_with_read_access", return_value=issue),
			patch("working_time.work_cockpit.frappe.get_doc", return_value=task),
		):
			result = promote_issue_to_task("ISS-1")

		self.assertEqual(
			sql.call_args_list[0].args,
			("select name from `tabIssue` where name=%s for update", ("ISS-1",)),
		)
		self.assertIn("from `tabTask`", sql.call_args_list[1].args[0])
		self.assertTrue(sql.call_args_list[1].kwargs["as_dict"])
		self.assertEqual(result, {"name": "TASK-1", "route": "/app/task/TASK-1", "created": False})

	def test_private_attachment_lookup_rechecks_task_and_issue_permission(self):
		task = FakeDocument(name="TASK-1", issue="ISS-1")
		files = [FakeDocument(name="FILE-1", file_url="/private/files/spec.pdf")]
		with (
			patch("working_time.work_cockpit.require_time_booking_identity"),
			patch("working_time.work_cockpit.frappe.get_doc", return_value=task),
			patch("working_time.work_cockpit.frappe.has_permission", return_value=True),
			patch("working_time.work_cockpit._issue_with_read_access") as issue_access,
			patch("working_time.work_cockpit.frappe.get_all", return_value=files) as get_all,
		):
			result = get_issue_attachments("TASK-1")

		issue_access.assert_called_once_with("ISS-1")
		self.assertEqual(get_all.call_args.kwargs["filters"]["is_private"], 1)
		self.assertEqual(result, files)


if __name__ == "__main__":
	unittest.main()
