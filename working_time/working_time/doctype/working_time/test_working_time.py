# Copyright (c) 2023, ALYF GmbH and Contributors
# See license.txt

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from frappe import ValidationError, _dict

from working_time.working_time.doctype.working_time.working_time import (
	WorkingTime,
	aggregate_time_logs,
	apply_project_billing_policy,
	calculate_hours,
	get_billable_duration,
	get_timesheet_description,
	group_timesheet_logs,
	should_enforce_billable_percentages,
	time_difference_seconds,
)
from working_time.working_time.doctype.working_time_log.working_time_log import WorkingTimeLog


class TestWorkingTime(unittest.TestCase):
	def test_time_log_starting_at_midnight_keeps_its_duration(self):
		log = _dict(from_time=timedelta(0), to_time=timedelta(hours=1), duration=0)

		WorkingTimeLog.remove_seconds(log)
		WorkingTimeLog.set_duration(log)

		self.assertEqual(log.from_time, timedelta(0))
		self.assertEqual(log.duration, 60 * 60)

	def test_time_difference_supports_regular_and_overnight_days(self):
		self.assertEqual(time_difference_seconds("08:00", "17:00"), 9 * 60 * 60)
		self.assertEqual(time_difference_seconds("22:00", "06:00"), 8 * 60 * 60)

	def test_native_task_description(self):
		self.assertEqual(
			get_timesheet_description("TASK-0001", ["Customer-visible note"]),
			"TASK-0001: Customer-visible note",
		)

	def test_calculate_hours_preserves_raw_actual_and_billable_time(self):
		actual, billable = calculate_hours(_dict(duration=7 * 60, billable="100%"))

		self.assertAlmostEqual(actual, 7 / 60)
		self.assertAlmostEqual(billable, 7 / 60)

	def test_calculate_hours_rejects_partial_or_overbilling(self):
		for billable in ("25%", "50%", "75%", "125%", "150%"):
			with self.subTest(billable=billable), self.assertRaises(ValidationError):
				calculate_hours(_dict(duration=7 * 60, billable=billable))

	def test_simple_project_switch_controls_billable_time(self):
		log = _dict(project="PROJ-0001", billable="100%")
		with patch(
			"working_time.working_time.doctype.working_time.working_time.frappe.db.get_value",
			return_value=(None, 0),
		):
			apply_project_billing_policy(log)
		self.assertEqual(log.billable, "0%")

		with patch(
			"working_time.working_time.doctype.working_time.working_time.frappe.db.get_value",
			return_value=(None, 1),
		):
			apply_project_billing_policy(log)
		self.assertEqual(log.billable, "0%")

		log.billable = None
		with patch(
			"working_time.working_time.doctype.working_time.working_time.frappe.db.get_value",
			return_value=(None, 1),
		):
			apply_project_billing_policy(log)
		self.assertEqual(log.billable, "100%")

	def test_rest_validation_uses_duration_first_day_boundaries(self):
		document = _dict(
			name="WT-0002",
			employee="EMP-0001",
			date="2026-08-02",
			check_in="08:00",
			time_logs=[_dict(duration=60 * 60, from_time=None)],
		)
		policy = _dict(min_rest_between_days=11 * 60 * 60)
		previous = _dict(name="WT-0001", date="2026-08-01", check_in="08:00", check_out="23:00")

		with (
			patch(
				"working_time.working_time.doctype.working_time.working_time.frappe.db.get_value",
				return_value=previous,
			) as get_value,
			self.assertRaises(ValidationError),
		):
			WorkingTime.validate_min_rest_between_days(document, policy)

		get_value.assert_called_once()

	def test_rest_validation_treats_overnight_checkout_as_next_day(self):
		document = _dict(
			name="WT-0002",
			employee="EMP-0001",
			date="2026-08-02",
			check_in="16:00",
			time_logs=[_dict(duration=60 * 60, from_time=None)],
		)
		policy = _dict(min_rest_between_days=11 * 60 * 60)
		previous = _dict(name="WT-0001", date="2026-08-01", check_in="22:00", check_out="06:00")

		with (
			patch(
				"working_time.working_time.doctype.working_time.working_time.frappe.db.get_value",
				return_value=previous,
			),
			self.assertRaises(ValidationError),
		):
			WorkingTime.validate_min_rest_between_days(document, policy)

	def test_timesheet_projects_share_one_non_overlapping_timeline(self):
		logs = [
			_dict(project="PROJ-A", duration=60 * 60, is_break=0),
			_dict(project="PROJ-B", duration=30 * 60, is_break=0),
			_dict(project=None, duration=15 * 60, is_break=1),
			_dict(project="PROJ-A", duration=30 * 60, is_break=0),
		]

		grouped = group_timesheet_logs(
			logs,
			work_date="2026-08-01",
			check_in="08:00",
			check_out="10:15",
			indicated_break=15 * 60,
		)

		self.assertEqual(
			[(start, end) for _, start, end in grouped["PROJ-A"]],
			[
				(datetime(2026, 8, 1, 8, 0), datetime(2026, 8, 1, 9, 0)),
				(datetime(2026, 8, 1, 9, 45), datetime(2026, 8, 1, 10, 15)),
			],
		)
		self.assertEqual(
			[(start, end) for _, start, end in grouped["PROJ-B"]],
			[(datetime(2026, 8, 1, 9, 0), datetime(2026, 8, 1, 9, 30))],
		)

	def test_timesheet_timeline_inserts_indicated_break_and_stays_within_checkout(self):
		logs = [
			_dict(project="PROJ-A", duration=4 * 60 * 60, is_break=0),
			_dict(project="PROJ-B", duration=4 * 60 * 60, is_break=0),
		]

		grouped = group_timesheet_logs(
			logs,
			work_date="2026-08-01",
			check_in="08:00",
			check_out="16:30",
			indicated_break=30 * 60,
		)

		self.assertEqual(grouped["PROJ-A"][0][1:], (datetime(2026, 8, 1, 8), datetime(2026, 8, 1, 12)))
		self.assertEqual(
			grouped["PROJ-B"][0][1:],
			(datetime(2026, 8, 1, 12, 30), datetime(2026, 8, 1, 16, 30)),
		)

	def test_timesheet_timeline_rejects_entries_after_checkout(self):
		logs = [_dict(project="PROJ-A", duration=9 * 60 * 60, is_break=0)]

		with self.assertRaises(ValidationError):
			group_timesheet_logs(
				logs,
				work_date="2026-08-01",
				check_in="08:00",
				check_out="17:00",
				indicated_break=30 * 60,
			)

	def test_timesheet_timeline_rejects_break_rows_above_indicated_break(self):
		logs = [
			_dict(project="PROJ-A", duration=60 * 60, is_break=0),
			_dict(project=None, duration=30 * 60, is_break=1),
		]

		with self.assertRaises(ValidationError):
			group_timesheet_logs(
				logs,
				work_date="2026-08-01",
				check_in="08:00",
				check_out="09:15",
				indicated_break=15 * 60,
			)

	def test_submitted_history_keeps_legacy_percentage_readable(self):
		legacy_log = _dict(duration=60 * 60, billable="50%")
		self.assertEqual(get_billable_duration(legacy_log, allow_legacy=True), 30 * 60)

		submitted = _dict(docstatus=1)
		submitted.get_doc_before_save = lambda: _dict(docstatus=1)
		submitting_draft = _dict(docstatus=1)
		submitting_draft.get_doc_before_save = lambda: _dict(docstatus=0)

		self.assertFalse(should_enforce_billable_percentages(submitted))
		self.assertTrue(should_enforce_billable_percentages(submitting_draft))

	def test_aggregate_time_logs(self):
		logs = [
			_dict(
				project="Project A",
				duration=3600,
				billable="100%",
				note="Internal Note 1",
			),
			_dict(
				project="Project A",
				duration=1800,
				billable="100%",
				note="Internal Note 2",
			),
			_dict(
				project="Project A",
				duration=1800,
				billable="100%",
				note="Internal Note 2",  # Duplicate, should be ignored
			),
			_dict(
				project="Project A",
				duration=3600,
				billable="100%",
				note="Internal Note 1",  # Not consecutive, should be added
			),
			_dict(
				project="Project B",
				task="Task B",
				duration=3600,
				billable="100%",
				note="+Customer Note 1",
			),
			_dict(
				project="Project B",
				task="Task B",
				duration=3600,
				billable="100%",
				note="+Customer Note 1",  # Duplicate, should be ignored
			),
			_dict(
				project="Project B",
				task="Task B",
				duration=900,
				billable="0%",
				customer_description="Explicit customer text",
				internal_note="Explicit internal text",
				note=None,
			),
		]

		result = aggregate_time_logs(logs)

		# Check Project A
		project_a = result[("Project A", None)]
		self.assertEqual(project_a["hours"], 3.0)
		self.assertEqual(
			project_a["internal_notes"], ["Internal Note 1", "Internal Note 2", "Internal Note 1"]
		)
		self.assertEqual(project_a["customer_notes"], [])

		# Check Project B
		project_b = result[("Project B", "Task B")]
		self.assertEqual(project_b["hours"], 2.25)
		self.assertEqual(project_b["internal_notes"], ["Explicit internal text"])
		self.assertEqual(project_b["customer_notes"], ["Customer Note 1", "Explicit customer text"])
