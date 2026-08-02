# Copyright (c) 2023, ALYF GmbH and contributors
# For license information, please see license.txt

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.model.docstatus import DocStatus
from frappe.model.document import Document
from frappe.utils.data import add_to_date, flt, format_duration, get_time, getdate

from working_time.working_time.number_card.number_cards import get_chart_data

HALF_DAY = 3.25
OVERTIME_FACTOR = 1.15
MAX_HALF_DAY = HALF_DAY * OVERTIME_FACTOR * 60 * 60
ONE_HOUR = 60 * 60


class WorkingTime(Document):
	def before_validate(self):
		self.break_time = self.working_time = self.project_time = self.billable_time = 0
		self.project_pct = self.billable_pct = 0

		for log in self.time_logs:
			log.cleanup_and_set_duration()
			log.duration = log.duration or 0
			migrate_legacy_note(log)
			apply_project_billing_policy(log)
			self.break_time += log.duration if log.is_break else 0
			if log.project and not log.is_break:
				self.project_time += log.duration
				self.billable_time += get_billable_duration(log)

		if self.check_in and self.check_out:
			gross = time_difference_seconds(self.check_in, self.check_out)
			self.break_time = float(self.indicated_break or 0)
			self.working_time = max(gross - self.break_time, 0)
		else:
			self.working_time = sum(float(log.duration or 0) for log in self.time_logs if not log.is_break)
		self.mandatory_break = get_mandatory_break(self.employee, self.working_time)
		self.unallocated_time = self.working_time - self.project_time

		if self.working_time:
			self.project_pct = round(self.project_time / self.working_time * 100, 0)
			self.billable_pct = round(self.billable_time / self.working_time * 100, 0)

	def validate(self):
		duplicate = frappe.db.exists(
			"Working Time",
			{"employee": self.employee, "date": self.date, "docstatus": ("!=", 2), "name": ("!=", self.name)},
		)
		if duplicate:
			frappe.throw(_("Working Time {0} already exists for this employee and date.").format(duplicate))

		for log in self.time_logs:
			if log.duration and log.duration < 0:
				frappe.throw(_("Please fix negative duration in row {0}").format(log.idx))

			validate_log_links(log)

		if self.docstatus == DocStatus.submitted():
			if not self.check_in or not self.check_out:
				frappe.throw(_("Start and end are required before submission."))
			if float(self.indicated_break or 0) < float(self.mandatory_break or 0):
				frappe.throw(_("The indicated break is shorter than the required break."))
			if abs(float(self.unallocated_time or 0)) > 1:
				frappe.throw(_("The complete net working time must be allocated before submission."))
			if any(not log.project for log in self.time_logs if log.duration and not log.is_break):
				frappe.throw(_("Every time entry requires a project before submission."))

		self.validate_working_time_policy()

	def validate_working_time_policy(self):
		policy_name = frappe.db.get_value("Employee", self.employee, "working_time_policy")
		if not policy_name:
			return

		policy = frappe.get_doc("Working Time Policy", policy_name)

		self.validate_blocked_day(policy)
		self.validate_holiday_block(policy)
		self.validate_max_working_time(policy)
		self.validate_mandatory_breaks(policy)
		self.validate_min_rest_between_days(policy)

	def validate_blocked_day(self, policy):
		if not policy.blocked_days:
			return

		day_name = getdate(self.date).strftime("%A")
		blocked_days = [row.blocked_day for row in policy.blocked_days]
		if day_name in blocked_days:
			frappe.throw(_("{0} is a blocked day according to the Working Time Policy").format(day_name))

	def validate_holiday_block(self, policy):
		if not policy.consider_holiday_list:
			return

		holiday_list = frappe.db.get_value("Employee", self.employee, "holiday_list")
		if not holiday_list:
			return

		is_holiday = frappe.db.exists(
			"Holiday",
			{"parent": holiday_list, "holiday_date": self.date, "weekly_off": 0},
		)
		if is_holiday:
			frappe.throw(
				_("{0} is a holiday according to your holiday list").format(
					frappe.utils.format_date(self.date)
				)
			)

	def validate_max_working_time(self, policy):
		if not policy.max_working_time_per_day:
			return

		if self.working_time > policy.max_working_time_per_day:
			frappe.throw(
				_("Working time ({0}) exceeds the maximum allowed ({1}) per day").format(
					format_duration(self.working_time),
					format_duration(policy.max_working_time_per_day),
				)
			)

	def validate_mandatory_breaks(self, policy):
		if not policy.mandatory_breaks:
			return

		for row in policy.mandatory_breaks:
			if self.working_time >= row.work_threshold and self.break_time < row.required_break_minutes:
				frappe.throw(
					_("Working time of {0} or more requires at least {1} of break time").format(
						format_duration(row.work_threshold),
						format_duration(row.required_break_minutes),
					)
				)

	def validate_min_rest_between_days(self, policy):
		if not policy.min_rest_between_days or not self.time_logs:
			return

		previous = frappe.db.get_value(
			"Working Time",
			{
				"employee": self.employee,
				"date": ("<", self.date),
				"docstatus": ("!=", 2),
				"name": ("!=", self.name),
			},
			["name", "date"],
			order_by="date desc",
			as_dict=True,
		)
		if not previous:
			return

		last_to_time = frappe.db.get_value(
			"Working Time Log",
			{"parent": previous.name, "to_time": ("is", "set")},
			"to_time",
			order_by="to_time desc",
		)
		if not last_to_time:
			return

		first_from_time = self.time_logs[0].from_time
		if not first_from_time:
			return

		prev_end = datetime.combine(getdate(previous.date), get_time(last_to_time))
		curr_start = datetime.combine(getdate(self.date), get_time(first_from_time))
		rest_seconds = (curr_start - prev_end).total_seconds()

		if rest_seconds < policy.min_rest_between_days:
			frappe.throw(
				_("Rest time since previous day ({0}) is less than the required minimum ({1})").format(
					format_duration(rest_seconds),
					format_duration(policy.min_rest_between_days),
				)
			)

	def on_submit(self):
		self.create_attendance()
		self.create_timesheets()

	def on_cancel(self):
		self.delete_draft_timesheets()
		self.cancel_attendance()

	def create_attendance(self):
		existing = frappe.db.exists(
			"Attendance",
			{"employee": self.employee, "attendance_date": self.date, "docstatus": ("!=", 2)},
		)

		if existing:
			frappe.db.set_value("Attendance", existing, "working_time", self.name)
		else:
			attendance = frappe.get_doc(
				{
					"doctype": "Attendance",
					"employee": self.employee,
					"status": "Present" if self.working_time > MAX_HALF_DAY else "Half Day",
					"attendance_date": self.date,
					"working_time": self.name,
				}
			)
			attendance.flags.ignore_permissions = True
			attendance.save()
			attendance.submit()

	def create_timesheets(self):
		logs_by_project = {}
		for log in self.time_logs:
			if log.duration and log.project and not log.is_break:
				logs_by_project.setdefault(log.project, []).append(log)

		for project, logs in logs_by_project.items():
			costing_rate = get_costing_rate(self.employee)
			customer, billing_rate = frappe.db.get_value(
				"Project",
				project,
				["customer", "billing_rate"],
			)
			cursor = datetime.combine(getdate(self.date), get_time(self.check_in))
			details = []
			for log in logs:
				hours, billable_hours = calculate_hours(log)
				end = cursor + timedelta(seconds=float(log.duration or 0))
				details.append(
					{
						"is_billable": int(billable_hours > 0),
						"project": project,
						"task": log.task,
						"helpdesk_ticket": log.helpdesk_ticket,
						"activity_type": "Default",
						"base_billing_rate": billing_rate,
						"base_costing_rate": costing_rate,
						"costing_rate": costing_rate,
						"billing_rate": billing_rate,
						"hours": hours,
						"from_time": cursor,
						"to_time": end,
						"billing_hours": billable_hours,
						"description": get_timesheet_description(
							log.task, [log.customer_description] if log.customer_description else []
						),
						"customer_description": log.customer_description,
						"internal_note": log.internal_note,
					}
				)
				cursor = end

			timesheet = frappe.get_doc(
				{
					"doctype": "Timesheet",
					"time_logs": details,
					"parent_project": project,
					"customer": customer,
					"employee": self.employee,
					"working_time": self.name,
				}
			).insert(ignore_permissions=True)
			timesheet.submit()

	def delete_draft_timesheets(self):
		for timesheet in frappe.get_list(
			"Timesheet", filters={"working_time": self.name, "docstatus": ("!=", DocStatus.cancelled())}
		):
			doc = frappe.get_doc("Timesheet", timesheet.name)
			from working_time.platform_operations import assert_timesheet_unclaimed

			assert_timesheet_unclaimed(doc)
			if doc.docstatus == DocStatus.submitted():
				doc.cancel()
			else:
				frappe.delete_doc("Timesheet", doc.name)

	def cancel_attendance(self):
		if frappe.has_permission("Attendance", "cancel"):
			# Cancelling will be done by the framework automatically
			return

		attendance_name = frappe.db.get_value(
			"Attendance", {"working_time": self.name, "docstatus": ("!=", DocStatus.cancelled())}
		)
		if not attendance_name:
			return

		attendance = frappe.get_doc("Attendance", attendance_name)
		attendance.flags.ignore_permissions = True
		attendance.cancel()


def get_costing_rate(employee):
	return frappe.get_value(
		"Activity Cost",
		{"activity_type": "Default", "employee": employee},
		"costing_rate",
	)


def get_billable_duration(log):
	if log.billable == "0%":
		return 0

	return log.duration * float(log.billable.rstrip("% ")) / 100


def time_difference_seconds(start, end) -> float:
	start_value = get_time(start)
	end_value = get_time(end)
	seconds = (
		datetime.combine(getdate(), end_value) - datetime.combine(getdate(), start_value)
	).total_seconds()
	return seconds if seconds >= 0 else seconds + 24 * ONE_HOUR


def get_mandatory_break(employee: str, working_seconds: float) -> float:
	policy_name = frappe.db.get_value("Employee", employee, "working_time_policy") if employee else None
	if not policy_name:
		return 0
	policy = frappe.get_doc("Working Time Policy", policy_name)
	required = 0
	for row in policy.mandatory_breaks or []:
		if working_seconds >= float(row.work_threshold or 0):
			required = max(required, float(row.required_break_minutes or 0))
	return required


def migrate_legacy_note(log) -> None:
	if (log.customer_description or log.internal_note) or not log.note:
		return
	log.customer_description, log.internal_note = parse_note(log.note)


def apply_project_billing_policy(log) -> None:
	if not log.project:
		log.billable = "0%"
		return
	project_type, billing_model = frappe.db.get_value(
		"Project", log.project, ["project_type", "billing_model"]
	) or (None, None)
	if project_type == "Internal" or billing_model != "Time and Material":
		log.billable = "0%"
	elif not log.billable:
		log.billable = "100%"


def validate_log_links(log) -> None:
	if log.task and frappe.db.get_value("Task", log.task, "project") != log.project:
		frappe.throw(_("Task in row {0} does not belong to the selected project.").format(log.idx))
	if log.helpdesk_ticket:
		from working_time.helpdesk import validate_ticket_booking

		validate_ticket_booking(log.helpdesk_ticket, log.project, log.task)


def parse_note(note: str | None) -> tuple[str | None, str | None]:
	"""Parse a note into customer note and internal note."""
	customer_note = None
	internal_note = None
	stripped_note = note.strip() if note else None
	if stripped_note:
		if stripped_note.startswith("+"):
			customer_note = stripped_note[1:].strip()
		else:
			internal_note = stripped_note

	return customer_note, internal_note


def get_timesheet_description(task: str | None, customer_notes: list[str]) -> str:
	"""Build a local Timesheet description from the native task and notes."""
	parts: list[str] = []
	if task:
		parts.append(str(task))
	if customer_notes:
		parts.append("; ".join(customer_notes))
	return ": ".join(parts) or "-"


def calculate_hours(log) -> tuple[float, float]:
	"""Return unrounded actual and billable hours from a time log.

	Commercial rounding belongs to Billing Review after the raw entries have
	been aggregated by customer, project, task and day.
	"""
	hours = float(log.duration or 0) / ONE_HOUR
	billing_hours = float(get_billable_duration(log) or 0) / ONE_HOUR

	return hours, billing_hours


def aggregate_time_logs(time_logs) -> dict[tuple[str | None, str | None], dict]:
	"""Aggregate time logs by native ERPNext project and task."""
	aggregated_time_logs = {
		# (log.project, log.task): {
		#     customer_notes: [],
		#     internal_notes: [],
		#     billable_hours: 0,
		#     hours: 0,
		# }
	}

	for log in time_logs:
		if log.duration and log.project:
			hours, billing_hours = calculate_hours(log)
			customer_note, internal_note = (
				(log.get("customer_description"), log.get("internal_note"))
				if log.get("customer_description") or log.get("internal_note")
				else parse_note(log.note)
			)

			if (log.project, log.task) in aggregated_time_logs:
				aggregated_time_logs[(log.project, log.task)]["hours"] += hours
				aggregated_time_logs[(log.project, log.task)]["billable_hours"] += billing_hours

				customer_notes = aggregated_time_logs[(log.project, log.task)]["customer_notes"]
				if customer_note and (not customer_notes or customer_notes[-1] != customer_note):
					customer_notes.append(customer_note)

				internal_notes = aggregated_time_logs[(log.project, log.task)]["internal_notes"]
				if internal_note and (not internal_notes or internal_notes[-1] != internal_note):
					internal_notes.append(internal_note)
			else:
				aggregated_time_logs[(log.project, log.task)] = {
					"hours": hours,
					"billable_hours": billing_hours,
					"customer_notes": [customer_note] if customer_note else [],
					"internal_notes": [internal_note] if internal_note else [],
				}

	return aggregated_time_logs


@frappe.whitelist()
def get_working_time_stats(employee: str, date: str):
	if not employee or not date:
		return []

	today = getdate(date)
	yesterday = getdate(add_to_date(today, days=-1))
	start_of_last_month = getdate(add_to_date(today.replace(day=1), months=-1))
	start_of_this_month = today.replace(day=1)
	end_of_last_month = getdate(add_to_date(start_of_this_month, days=-1))

	working_time_avg_last_month = get_chart_data(
		employee, start_of_last_month, end_of_last_month, "working_time"
	)
	break_time_avg_last_month = get_chart_data(employee, start_of_last_month, end_of_last_month, "break_time")
	billing_time_avg_last_month = get_chart_data(
		employee, start_of_last_month, end_of_last_month, "billable_time"
	)
	billing_time_ratio_last_month = (
		billing_time_avg_last_month / working_time_avg_last_month if working_time_avg_last_month else 0
	)

	stats = [
		{
			"timespan": _("Last Month"),
			"daily_working_time": {
				"value": flt(working_time_avg_last_month, 2),
			},
			"billing_time_ratio": {
				"value": flt(billing_time_ratio_last_month * 100, 2),
			},
			"daily_break_time": {
				"value": flt(break_time_avg_last_month, 2),
			},
		}
	]
	if yesterday.month == today.month:
		working_time_avg_this_month = get_chart_data(employee, start_of_this_month, yesterday, "working_time")
		break_time_avg_this_month = get_chart_data(employee, start_of_this_month, yesterday, "break_time")
		billing_time_avg_this_month = get_chart_data(
			employee, start_of_this_month, yesterday, "billable_time"
		)
		billing_time_ratio_this_month = (
			billing_time_avg_this_month / working_time_avg_this_month if working_time_avg_this_month else 0
		)

		stats.append(
			{
				"timespan": _("This Month"),
				"daily_working_time": {
					"value": flt(working_time_avg_this_month, 2),
					"pct_change": get_pct_change(working_time_avg_this_month, working_time_avg_last_month),
				},
				"billing_time_ratio": {
					"value": flt(billing_time_ratio_this_month * 100, 2),
					"pct_change": get_pct_change(
						billing_time_ratio_this_month, billing_time_ratio_last_month
					),
				},
				"daily_break_time": {
					"value": flt(break_time_avg_this_month, 2),
					"pct_change": get_pct_change(break_time_avg_this_month, break_time_avg_last_month),
				},
			},
		)

	return stats


def get_pct_change(new, old):
	return flt(-100 * (1 - new / old), 2) if old else 0
