# Copyright (c) 2023, ALYF GmbH and Contributors
# See license.txt

import unittest

from frappe import _dict

from working_time.working_time.doctype.working_time.working_time import (
	aggregate_time_logs,
	calculate_hours,
	get_timesheet_description,
)


class TestWorkingTime(unittest.TestCase):
	def test_native_task_description(self):
		self.assertEqual(
			get_timesheet_description("TASK-0001", ["Customer-visible note"]),
			"TASK-0001: Customer-visible note",
		)

	def test_calculate_hours_preserves_raw_actual_and_billable_time(self):
		actual, billable = calculate_hours(_dict(duration=7 * 60, billable="50%"))

		self.assertAlmostEqual(actual, 7 / 60)
		self.assertAlmostEqual(billable, 3.5 / 60)

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
		self.assertEqual(project_b["hours"], 2.0)
		self.assertEqual(project_b["internal_notes"], [])
		self.assertEqual(project_b["customer_notes"], ["Customer Note 1"])
