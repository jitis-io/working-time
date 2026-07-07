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
	frappe.db = types.SimpleNamespace(get_value=lambda *args, **kwargs: None)
	frappe.db.set_value = lambda *args, **kwargs: None
	frappe.form_dict = {}
	frappe.local = types.SimpleNamespace(request=None)
	frappe.get_request_header = lambda *args, **kwargs: None
	frappe.get_all = lambda *args, **kwargs: []
	frappe.get_doc = lambda *args, **kwargs: None
	frappe.enqueue = lambda *args, **kwargs: None
	frappe.whitelist = lambda *args, **kwargs: (lambda fn: fn)
	sys.modules["frappe"] = frappe


_bootstrap_frappe_stub()

from working_time.openproject_sync import (
	_enqueue_webhook_action,
	_parse_duration,
	_project_customer,
	_row_changes,
	_task_status,
	_time_entry_reconcile_params,
)


class Row:
	def __init__(self, **values):
		self.__dict__.update(values)


class TestOpenProjectSync(unittest.TestCase):
	def test_project_customer_uses_project_identifier(self):
		project_payload = {"identifier": "K-2601002", "name": "K-2601002"}

		with patch("working_time.openproject_sync._customer_name_by_identifier") as lookup:
			lookup.side_effect = lambda value: value if value == "K-2601002" else None

			self.assertEqual(_project_customer(project_payload), "K-2601002")

		lookup.assert_called_once_with("K-2601002")

	def test_project_customer_uses_parent_project_identifier_for_subprojects(self):
		project_payload = {
			"identifier": "arbeitspaket-4",
			"name": "Arbeitspaket 4",
			"_embedded": {
				"parent": {
					"identifier": "k-2601002",
					"name": "K-2601002",
				}
			},
			"_links": {
				"parent": {
					"href": "/api/v3/projects/9",
					"title": "K-2601002",
				}
			},
		}

		calls = []

		def lookup(value):
			calls.append(value)
			return "K-2601002" if value in {"k-2601002", "K-2601002"} else None

		with patch("working_time.openproject_sync._customer_name_by_identifier", side_effect=lookup):
			self.assertEqual(_project_customer(project_payload), "K-2601002")

		self.assertEqual(calls, ["arbeitspaket-4", "Arbeitspaket 4", "k-2601002"])

	def test_project_customer_ignores_non_project_parent(self):
		project_payload = {
			"identifier": "arbeitspaket-4",
			"name": "Arbeitspaket 4",
			"_links": {
				"parent": {
					"href": "/api/v3/portfolios/36",
					"title": "02-Kunden",
				}
			},
		}

		calls = []

		with patch(
			"working_time.openproject_sync._customer_name_by_identifier",
			side_effect=lambda value: calls.append(value) or None,
		):
			self.assertIsNone(_project_customer(project_payload))

		self.assertEqual(calls, ["arbeitspaket-4", "Arbeitspaket 4"])

	def test_parse_duration_supports_openproject_iso_duration(self):
		self.assertEqual(_parse_duration("PT1H30M"), 1.5)
		self.assertEqual(_parse_duration("P1DT2H"), 26)
		self.assertEqual(_parse_duration("0.75"), 0.75)

	def test_time_entry_reconcile_params_include_updated_cursor_with_overlap(self):
		params = _time_entry_reconcile_params("2026-07-07 12:00:00")

		self.assertEqual(params["sortBy"], '[["updated_at", "asc"], ["id", "asc"]]')
		self.assertIn('"updated_at"', params["filters"])
		self.assertIn('"operator": ">="', params["filters"])
		self.assertIn("2026-07-07T11:55:00Z", params["filters"])

	def test_time_entry_reconcile_params_are_full_scan_without_cursor(self):
		params = _time_entry_reconcile_params(None)

		self.assertEqual(params, {"sortBy": '[["updated_at", "asc"], ["id", "asc"]]'})

	def test_row_changes_detects_updated_synced_timesheet_values(self):
		row = Row(hours=1.0, description="Old text", project="Project A")

		self.assertEqual(
			_row_changes(
				row,
				{"hours": 1.5, "description": "New text", "project": "Project A"},
			),
			{"hours": 1.5, "description": "New text"},
		)

	def test_task_status_maps_openproject_status(self):
		self.assertEqual(_task_status({"_links": {"status": {"title": "Done"}}}), "Completed")
		self.assertEqual(_task_status({"_links": {"status": {"title": "In progress"}}}), "Working")
		self.assertEqual(_task_status({"_links": {"status": {"title": "New"}}}), "Open")

	def test_webhook_dispatch_enqueues_time_entry_updates(self):
		with patch("working_time.openproject_sync.enqueue_sync_time_entry") as enqueue:
			result = _enqueue_webhook_action(
				"OpenProject",
				{"action": "time_entry:updated", "time_entry": {"id": 42}},
			)

		enqueue.assert_called_once_with("OpenProject", "42")
		self.assertEqual(result, {"queued": True, "action": "time_entry:updated", "time_entry_id": "42"})

	def test_webhook_dispatch_enqueues_time_entry_from_hal_link(self):
		with patch("working_time.openproject_sync.enqueue_sync_time_entry") as enqueue:
			result = _enqueue_webhook_action(
				"OpenProject",
				{
					"action": "time_entry:updated",
					"_links": {"timeEntry": {"href": "/api/v3/time_entries/42"}},
				},
			)

		enqueue.assert_called_once_with("OpenProject", "42")
		self.assertEqual(result, {"queued": True, "action": "time_entry:updated", "time_entry_id": "42"})

	def test_webhook_dispatch_deletes_work_package(self):
		with patch(
			"working_time.openproject_sync._delete_work_package", return_value={"deleted": True}
		) as delete:
			result = _enqueue_webhook_action(
				"OpenProject",
				{"action": "work_package:deleted", "work_package": {"id": 99}},
			)

		delete.assert_called_once_with("99")
		self.assertEqual(result, {"action": "work_package:deleted", "deleted": True})
