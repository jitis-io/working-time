import sys
import types
import unittest
from contextlib import nullcontext
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
	frappe.db.exists = lambda *args, **kwargs: False
	frappe.db.set_value = lambda *args, **kwargs: None
	frappe.form_dict = {}
	frappe.local = types.SimpleNamespace(request=None)
	frappe.get_request_header = lambda *args, **kwargs: None
	frappe.get_all = lambda *args, **kwargs: []
	frappe.get_doc = lambda *args, **kwargs: None
	frappe.enqueue = lambda *args, **kwargs: None
	frappe.whitelist = lambda *args, **kwargs: lambda fn: fn
	sys.modules["frappe"] = frappe


_bootstrap_frappe_stub()

from working_time.openproject_sync import (
	_enqueue_webhook_action,
	_ensure_parent_task_is_group,
	_is_deleted_object,
	_parse_duration,
	_project_customer,
	_record_webhook_event,
	_row_changes,
	_task_status,
	_time_entry_reconcile_params,
	_webhook_object,
	reconcile_openproject_time_entry_deletions,
	sync_time_entry_from_openproject,
)


class Row:
	def __init__(self, **values):
		self.__dict__.update(values)

	def get(self, key, default=None):
		return getattr(self, key, default)


class ParentTask(Row):
	def __init__(self, **values):
		super().__init__(**values)
		self.flags = types.SimpleNamespace(ignore_permissions=False)
		self.saved = False

	def save(self, **kwargs):
		self.saved = True


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

	def test_existing_parent_task_is_marked_group_before_child_save(self):
		child = Row(parent_task="TASK-1")
		parent = ParentTask(is_group=0)

		with (
			patch("working_time.openproject_sync.frappe.db.get_value", return_value=0),
			patch("working_time.openproject_sync.frappe.get_doc", return_value=parent),
		):
			_ensure_parent_task_is_group(child)

		self.assertEqual(parent.is_group, 1)
		self.assertTrue(parent.flags.ignore_permissions)
		self.assertTrue(parent.saved)

	def test_webhook_dispatch_enqueues_time_entry_updates(self):
		result = _enqueue_webhook_action(
			"OpenProject",
			{"action": "time_entry:updated", "time_entry": {"id": 42}},
		)

		self.assertEqual(result, {"queued": True, "action": "time_entry:updated", "time_entry_id": "42"})

	def test_webhook_dispatch_enqueues_time_entry_from_hal_link(self):
		result = _enqueue_webhook_action(
			"OpenProject",
			{
				"action": "time_entry:updated",
				"_links": {"timeEntry": {"href": "/api/v3/time_entries/42"}},
			},
		)

		self.assertEqual(result, {"queued": True, "action": "time_entry:updated", "time_entry_id": "42"})

	def test_webhook_dispatch_queues_work_package_delete(self):
		with (
			patch("working_time.openproject_sync._remember_deleted_object") as remember,
		):
			result = _enqueue_webhook_action(
				"OpenProject",
				{"action": "work_package:deleted", "work_package": {"id": 99}},
			)

		remember.assert_called_once_with("work_package", "99")
		self.assertEqual(
			result,
			{"queued": True, "action": "work_package:deleted", "work_package_id": "99"},
		)

	def test_webhook_dispatch_queues_time_entry_delete(self):
		with (
			patch("working_time.openproject_sync._remember_deleted_object") as remember,
		):
			result = _enqueue_webhook_action(
				"OpenProject",
				{"action": "time_entry:deleted", "time_entry": {"id": 42}},
			)

		remember.assert_called_once_with("time_entry", "42")
		self.assertEqual(
			result,
			{"queued": True, "action": "time_entry:deleted", "time_entry_id": "42"},
		)

	def test_webhook_dispatch_ignores_deleted_work_package_update(self):
		with (
			patch("working_time.openproject_sync._is_deleted_object", return_value=True),
			patch("working_time.openproject_sync.enqueue_sync_work_package") as enqueue,
		):
			result = _enqueue_webhook_action(
				"OpenProject",
				{"action": "work_package:updated", "work_package": {"id": 99}},
			)

		enqueue.assert_not_called()
		self.assertEqual(
			result,
			{
				"ignored": True,
				"action": "work_package:updated",
				"work_package_id": "99",
				"reason": "deleted_object",
			},
		)

	def test_webhook_dispatch_ignores_deleted_time_entry_update(self):
		with (
			patch("working_time.openproject_sync._is_deleted_object", return_value=True),
			patch("working_time.openproject_sync.enqueue_sync_time_entry") as enqueue,
		):
			result = _enqueue_webhook_action(
				"OpenProject",
				{"action": "time_entry:updated", "time_entry": {"id": 42}},
			)

		enqueue.assert_not_called()
		self.assertEqual(
			result,
			{
				"ignored": True,
				"action": "time_entry:updated",
				"time_entry_id": "42",
				"reason": "deleted_object",
			},
		)

	def test_deleted_object_lookup_falls_back_when_doctype_is_missing(self):
		with patch("working_time.openproject_sync.frappe.db.exists", side_effect=Exception("missing")):
			self.assertFalse(_is_deleted_object("time_entry", "42"))

	def test_queued_time_entry_update_stops_at_tombstone(self):
		with (
			patch("working_time.openproject_sync._site_name", return_value="OpenProject"),
			patch("working_time.openproject_sync._sync_lock", return_value=nullcontext()),
			patch("working_time.openproject_sync._is_deleted_object", return_value=True),
			patch("working_time.openproject_sync.OpenProjectClient") as client,
		):
			result = sync_time_entry_from_openproject("42", "OpenProject")

		client.assert_not_called()
		self.assertEqual(result, {"ignored": True, "reason": "deleted_object"})

	def test_full_time_entry_reconciliation_deletes_missing_ids(self):
		with (
			patch("working_time.openproject_sync._site_name", return_value="OpenProject"),
			patch("working_time.openproject_sync.OpenProjectClient"),
			patch("working_time.openproject_sync._iterate", return_value=iter([{"id": 1}, {"id": 2}])),
			patch(
				"working_time.openproject_sync._mapped_openproject_ids",
				return_value={"1", "2", "3"},
			),
			patch(
				"working_time.openproject_sync.delete_time_entry_from_openproject",
				return_value={"deleted": True},
			) as delete,
			patch(
				"working_time.openproject_sync._full_delete_reconciliation_enabled",
				return_value=True,
			),
		):
			result = reconcile_openproject_time_entry_deletions("OpenProject")

		delete.assert_called_once_with("3")
		self.assertEqual(result, {"checked": 2, "deleted": 1, "missing": 0, "locked": 0})

	def test_full_time_entry_reconciliation_is_disabled_by_default(self):
		with (
			patch("working_time.openproject_sync._site_name", return_value="OpenProject"),
			patch(
				"working_time.openproject_sync._full_delete_reconciliation_enabled",
				return_value=False,
			),
			patch("working_time.openproject_sync.OpenProjectClient") as client,
		):
			result = reconcile_openproject_time_entry_deletions("OpenProject")

		client.assert_not_called()
		self.assertEqual(
			result,
			{"disabled": True, "reason": "full_delete_reconciliation_not_enabled"},
		)

	def test_webhook_object_extracts_subject_for_visibility(self):
		self.assertEqual(
			_webhook_object({"action": "time_entry:updated", "time_entry": {"id": 42}}),
			("time_entry", "42"),
		)

	def test_record_webhook_event_inserts_visible_event(self):
		inserted = []

		class EventDoc(Row):
			def __init__(self, **values):
				super().__init__(**values)
				self.flags = types.SimpleNamespace(ignore_permissions=False)

			def insert(self, **kwargs):
				inserted.append(self)

		with patch(
			"working_time.openproject_sync.frappe.get_doc", side_effect=lambda values: EventDoc(**values)
		):
			_record_webhook_event(
				"OpenProject",
				{"action": "time_entry:updated", "time_entry": {"id": 42}},
				"Queued",
				{"queued": True},
			)

		self.assertEqual(inserted[0].doctype, "OpenProject Webhook Event")
		self.assertEqual(inserted[0].action, "time_entry:updated")
		self.assertEqual(inserted[0].object_type, "time_entry")
		self.assertEqual(inserted[0].object_id, "42")
		self.assertEqual(inserted[0].status, "Queued")
