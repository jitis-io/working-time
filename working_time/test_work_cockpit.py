import json
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from working_time.test_platform_operations import FakeDocument, _bootstrap_frappe_stub

_bootstrap_frappe_stub()

import frappe

if getattr(frappe, "__file__", None):
	from frappe.tests import IntegrationTestCase
else:
	IntegrationTestCase = unittest.TestCase

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

from working_time.hooks import app_include_css, app_title, working_time_custom_fields
from working_time.work_cockpit import (
	_apply_time_and_billing_context,
	_assigned_filters,
	_filter_view,
	_get_external_items,
	_get_native_items,
	_normalize_external_item,
	_permission_aware_list,
	_safe_task_description,
	complete_task,
	create_quick_task,
	get_issue_attachments,
	get_quick_task_context,
	get_work_cockpit,
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
		self.assertEqual(page["title"], "My Work")
		self.assertEqual(app_title, "JITIS Work")
		self.assertEqual(app_include_css, "/assets/working_time/css/jitis_work.css")
		self.assertIn(
			{
				"hidden": 0,
				"is_query_report": 0,
				"label": "My Work",
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

	def test_system_manager_personal_scope_still_requires_exact_assignment(self):
		with patch("working_time.work_cockpit.is_system_manager", return_value=True):
			filters = _assigned_filters(("Open",), "manager@example.com")

		self.assertEqual(filters["_assign"], ["like", '%"manager@example.com"%'])

	def test_system_manager_may_explicitly_open_team_scope(self):
		with patch("working_time.work_cockpit.is_system_manager", return_value=True):
			filters = _assigned_filters(("Open",), "manager@example.com", "team")

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
		working = item(name="TASK-W", status="Working")

		with patch("working_time.work_cockpit.nowdate", return_value="2026-08-11"):
			self.assertEqual(_filter_view([due, future, worked, working], "today"), [due, worked, working])

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
				"priority": 7,
				"customer": 8,
				"project": 9,
				"project_name": 10,
				"assigned_to": 11,
				"billing_statuses": 12,
				"is_personal": "false",
				"operational_state": "Provider secret state",
				"unknown_secret": "must not leave provider boundary",
				"route": "javascript:alert(document.cookie)",
				"commercial_context": {
					"contract": "CON-1",
					"sales_invoices": 13,
					"api_token": "must not leave provider boundary",
				},
			},
			"github.provider",
		)

		self.assertEqual(result["operational_state"], "Normal")
		self.assertEqual(result["description"], "")
		self.assertTrue(result["description_is_plain_text"])
		self.assertFalse(result["is_personal"])
		self.assertEqual(result["priority"], "7")
		self.assertEqual(result["customer"], "8")
		self.assertEqual(result["project"], "9")
		self.assertEqual(result["project_name"], "10")
		self.assertEqual(result["assigned_to"], [])
		self.assertEqual(result["billing_statuses"], [])
		self.assertEqual(result["commercial_context"]["sales_invoices"], [])
		self.assertNotIn("unknown_secret", result)
		self.assertIsNone(result["route"])
		self.assertNotIn("api_token", result["commercial_context"])
		self.assertIsNone(_normalize_external_item({"title": "Missing ID"}, "github.provider"))
		blocked = _normalize_external_item(
			{"external_id": "GH-3", "title": "Blocked issue", "operational_state": "Blocked"},
			"github.provider",
		)
		self.assertEqual(blocked["operational_state"], "Blockiert")

	def test_external_description_is_allowlisted_without_leaking_unknown_fields(self):
		result = _normalize_external_item(
			{
				"external_id": "GH-4",
				"title": "Document API",
				"description": "Explain the API contract",
				"private_token": "do not expose",
			},
			"github.provider",
		)

		self.assertEqual(result["description"], "Explain the API contract")
		self.assertNotIn("private_token", result)

	def test_native_issue_and_task_items_expose_description_and_project_name(self):
		issue = FakeDocument(
			name="ISS-1",
			subject="Router offline",
			description="<p>Customer description</p>",
			customer="CUST-1",
			project="PROJ-1",
			priority="High",
			status="Open",
			working_time_operational_state="Normal",
			working_time_planned_date=None,
			opening_date="2026-08-11",
			_assign='["dev@example.com"]',
		)
		task = FakeDocument(
			name="TASK-1",
			subject="Replace router",
			description="<p>Planned work</p>",
			project="PROJ-1",
			issue="ISS-1",
			priority="Medium",
			status="Open",
			working_time_operational_state="Normal",
			exp_start_date=None,
			exp_end_date="2026-08-11 18:00:00",
			_assign='["dev@example.com"]',
		)
		calls = []

		def get_list(doctype, **kwargs):
			calls.append((doctype, kwargs))
			return [issue] if doctype == "Issue" else [task]

		with (
			patch("working_time.work_cockpit._permission_aware_list", side_effect=get_list),
			patch(
				"working_time.work_cockpit._project_context",
				return_value={
					"PROJ-1": {
						"project_name": "Customer Support",
						"customer": "CUST-1",
						"sales_invoices": [],
					}
				},
			),
			patch("working_time.work_cockpit._apply_time_and_billing_context"),
		):
			items = _get_native_items("dev@example.com")

		self.assertIn("description", calls[0][1]["fields"])
		self.assertIn("description", calls[1][1]["fields"])
		self.assertEqual(items[0]["description"], "<p>Customer description</p>")
		self.assertEqual(items[1]["description"], "<p>Planned work</p>")
		self.assertEqual(items[1]["project_name"], "Customer Support")
		self.assertEqual(items[1]["due_date"], "2026-08-11")

	def test_all_view_defaults_to_personal_scope_and_is_sorted(self):
		later = item(name="TASK-Z", title="Zulu", due_date=None)
		earlier = item(name="TASK-A", title="Alpha", due_date="2026-08-12")
		with (
			patch("working_time.work_cockpit.require_time_booking_identity", return_value="dev@example.com"),
			patch("working_time.work_cockpit.is_system_manager", return_value=True),
			patch("working_time.work_cockpit.get_user_employee", return_value="EMP-1"),
			patch("working_time.work_cockpit.frappe.has_permission", return_value=True),
			patch("working_time.work_cockpit._get_native_items", return_value=[later, earlier]) as native,
			patch("working_time.work_cockpit._get_external_items", return_value=([], [])),
		):
			result = get_work_cockpit(view="all")

		native.assert_called_once_with("dev@example.com", "mine")
		self.assertEqual(result["scope"], "mine")
		self.assertTrue(result["can_view_team"])
		self.assertEqual(
			result["capabilities"],
			{"can_create_task": True, "can_update_task": True, "can_book_time": True},
		)
		self.assertEqual([row["name"] for row in result["items"]], ["TASK-A", "TASK-Z"])

	def test_non_manager_cannot_open_team_scope(self):
		with (
			patch("working_time.work_cockpit.require_time_booking_identity", return_value="dev@example.com"),
			patch("working_time.work_cockpit.is_system_manager", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			get_work_cockpit(scope="team")

	def test_personal_scope_excludes_external_items_without_positive_assignment(self):
		personal = item(
			source="github",
			item_type="External",
			name="GH-MINE",
			is_personal=True,
		)
		other = item(
			source="github",
			item_type="External",
			name="GH-OTHER",
			is_personal=False,
		)
		with (
			patch("working_time.work_cockpit.require_time_booking_identity", return_value="dev@example.com"),
			patch("working_time.work_cockpit.is_system_manager", return_value=True),
			patch("working_time.work_cockpit._get_native_items", return_value=[]),
			patch(
				"working_time.work_cockpit._get_external_items",
				return_value=([personal, other], []),
			),
		):
			personal_result = get_work_cockpit(view="all", scope="mine")
			team_result = get_work_cockpit(view="all", scope="team")

		self.assertEqual([row["name"] for row in personal_result["items"]], ["GH-MINE"])
		self.assertEqual(
			[row["name"] for row in team_result["items"]],
			["GH-MINE", "GH-OTHER"],
		)

	def test_quick_task_context_defaults_the_only_internal_project(self):
		projects = [
			FakeDocument(
				name="INTERNAL",
				project_name="JITIS Intern",
				customer=None,
				project_type="Internal",
			),
			FakeDocument(
				name="CUSTOMER",
				project_name="Customer Work",
				customer="CUST-1",
				project_type="External",
			),
		]
		with (
			patch("working_time.work_cockpit.require_time_booking_identity"),
			patch("working_time.work_cockpit.frappe.has_permission", return_value=True),
			patch("working_time.work_cockpit._quick_task_projects", return_value=projects),
		):
			context = get_quick_task_context()

		self.assertEqual(context["default_project"], "INTERNAL")
		self.assertEqual(len(context["projects"]), 2)

	def test_quick_task_description_is_escaped_html(self):
		self.assertEqual(
			_safe_task_description("First line\n<script>alert(1)</script>"),
			"<p>First line<br>&lt;script&gt;alert(1)&lt;/script&gt;</p>",
		)

	def test_quick_task_is_created_in_open_project_and_assigned_to_current_user(self):
		project = FakeDocument(name="INTERNAL", status="Open")
		task = FakeDocument(name="TASK-NEW", subject="Prepare invoices", priority="High")
		assign = Mock()
		assign_module = types.ModuleType("frappe.desk.form.assign_to")
		assign_module.add = assign

		def get_doc(value, name=None):
			if value == "Project":
				self.assertEqual(name, "INTERNAL")
				return project
			self.assertEqual(value["description"], "<p>Check all billable entries</p>")
			self.assertEqual(value["exp_end_date"], "2026-08-20")
			return task

		with (
			patch.dict(
				sys.modules,
				{
					"frappe.desk": types.ModuleType("frappe.desk"),
					"frappe.desk.form": types.ModuleType("frappe.desk.form"),
					"frappe.desk.form.assign_to": assign_module,
				},
			),
			patch(
				"working_time.work_cockpit.require_time_booking_identity",
				return_value="dev@example.com",
			),
			patch("working_time.work_cockpit.frappe.has_permission", return_value=True),
			patch("working_time.work_cockpit.frappe.get_doc", side_effect=get_doc),
		):
			result = create_quick_task(
				"Prepare invoices",
				"INTERNAL",
				description="Check all billable entries",
				due_date="2026-08-20",
				priority="High",
			)

		self.assertTrue(task.inserted)
		assign.assert_called_once()
		self.assertEqual(assign.call_args.args[0]["assign_to"], ["dev@example.com"])
		self.assertEqual(result["route"], "/app/task/TASK-NEW")

	def test_complete_task_uses_document_save_and_is_idempotent(self):
		task = FakeDocument(
			name="TASK-1",
			status="Open",
			project="INTERNAL",
			flags=FakeDocument(),
		)
		with (
			patch(
				"working_time.work_cockpit.require_time_booking_identity",
				return_value="dev@example.com",
			),
			patch("working_time.work_cockpit.frappe.get_doc", return_value=task),
			patch("working_time.work_cockpit.frappe.has_permission", return_value=True),
			patch("working_time.work_cockpit.frappe.db.get_value", return_value="Internal"),
			patch("working_time.work_cockpit.nowdate", return_value="2026-08-17"),
		):
			first = complete_task("TASK-1")
			second = complete_task("TASK-1")

		self.assertTrue(first["changed"])
		self.assertTrue(task.saved)
		self.assertEqual(task.completed_on, "2026-08-17")
		self.assertEqual(task.completed_by, "dev@example.com")
		self.assertEqual(task.closing_date, "2026-08-17")
		self.assertTrue(task.flags.from_project)
		self.assertFalse(second["changed"])

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


@unittest.skipUnless(getattr(frappe, "__file__", None), "requires the clean Frappe bench")
class TestWorkCockpitIntegration(IntegrationTestCase):
	def test_completing_last_task_keeps_internal_umbrella_project_open(self):
		from erpnext.projects.doctype.project.test_project import make_project

		project = make_project(
			{
				"project_name": f"JITIS Internal Work {frappe.generate_hash(length=8)}",
				"start_date": frappe.utils.nowdate(),
			}
		)
		project.project_type = "Internal"
		project.percent_complete_method = "Task Completion"
		project.save()
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": f"Internal task {frappe.generate_hash(length=8)}",
				"project": project.name,
				"status": "Open",
			}
		).insert()

		result = complete_task(task.name)
		task.reload()
		project.reload()

		self.assertTrue(result["changed"])
		self.assertEqual(task.status, "Completed")
		self.assertEqual(str(task.completed_on), frappe.utils.nowdate())
		self.assertEqual(task.completed_by, frappe.session.user)
		self.assertEqual(project.status, "Open")


if __name__ == "__main__":
	unittest.main()
