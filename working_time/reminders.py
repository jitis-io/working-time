import calendar
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.translate import print_language
from frappe.utils.data import get_url


def create_daily_drafts():
	settings = frappe.get_single("Working Time Settings")
	if not settings.create_daily_drafts:
		return
	today = date.today()
	for employee in frappe.get_all(
		"Employee", filters={"status": "Active", "user_id": ("is", "set")}, pluck="name"
	):
		if not frappe.db.exists(
			"Working Time", {"employee": employee, "date": today, "docstatus": ("!=", 2)}
		):
			frappe.get_doc({"doctype": "Working Time", "employee": employee, "date": today}).insert(
				ignore_permissions=True
			)


def is_last_working_day(d: date, absent_days: list[date]) -> bool:
	"""Check if a date is the last working day of the month.

	The last working day is the last non-absent day of the month.

	Args:
	- d: The date to check
	- absent_days: List of absent days (including weekends, holidays, and leaves)
	"""
	# Get the last day of the month
	last_dom = calendar.monthrange(d.year, d.month)[1]
	last_date = date(d.year, d.month, last_dom)

	# Find the last working day by moving backwards from the last day
	# until we hit a working day
	current = last_date
	while current >= d and current in absent_days:
		current -= timedelta(days=1)

	return current == d


def send_month_end_reminders():
	"""Send working time submission reminders to employees.

	This method is called every day. If it's the last working day for an employee,
	it sends a reminder to submit their working time entries before the month ends.
	"""
	today = date.today()
	last_dom = calendar.monthrange(today.year, today.month)[1]
	last_date = date(today.year, today.month, last_dom)

	for employee, holiday_list, prefered_email, first_name, user_id, reports_to in frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "holiday_list", "prefered_email", "first_name", "user_id", "reports_to"],
		as_list=True,
	):
		holidays = get_holiday_dates(holiday_list, today, last_date)
		leaves = get_leaves(employee, today, last_date)
		absent_days = list(set(holidays + leaves))

		if not is_last_working_day(today, absent_days):
			continue

		language = None
		if user_id:
			language = frappe.db.get_value("User", user_id, "language")

		reply_to = frappe.db.get_value("Employee", reports_to, "prefered_email") if reports_to else None

		with print_language(language):
			frappe.sendmail(
				recipients=prefered_email,
				reply_to=reply_to,
				subject=_("Remember to submit your working time"),
				message=_(
					"""Dear {first_name},

{month} is almost over. Please remember to submit your <a href='{url}'>working time</a>.

Thanks in advance!"""
				).format(
					first_name=first_name,
					month=_(today.strftime("%B")),
					url=get_url(f"/app/working-time?employee={employee}&docstatus=0"),
				),
			)


def get_holiday_dates(holiday_list: str, first_date: date, last_date: date) -> list[date]:
	"""Get all holiday dates for a given holiday list and date range.

	Args:
	- holiday_list: The name of the holiday list to check
	- first_date: The start date of the range
	- last_date: The end date of the range

	Returns:
	- A list of holiday dates
	"""
	return frappe.get_all(
		"Holiday",
		filters=[
			("parent", "=", holiday_list),
			("holiday_date", ">=", first_date),
			("holiday_date", "<=", last_date),
		],
		pluck="holiday_date",
	)


def get_leaves(employee: str, first_date: date, last_date: date) -> list[date]:
	return frappe.get_all(
		"Attendance",
		filters=[
			("employee", "=", employee),
			("attendance_date", ">=", first_date),
			("attendance_date", "<=", last_date),
			("status", "=", "On Leave"),
			("docstatus", "=", 1),
		],
		pluck="attendance_date",
	)


def send_stale_reminders(cutoff_days: int = 3):
	"""Send reminders to employees to submit their working time entries.

	This method is called every day. If an employee has one or more draft working
	time entries older than the configured deadline, it sends one reminder for all
	of them.
	"""
	settings = frappe.get_single("Working Time Settings")
	if not settings.send_reminders:
		return
	cutoff_days = int(settings.submission_deadline_days or cutoff_days)
	today = date.today()
	stale_entries_by_employee = {}
	for working_time, employee in frappe.get_all(
		"Working Time",
		filters=[
			("docstatus", "=", 0),
			("date", "<=", today - timedelta(days=cutoff_days)),
		],
		fields=["name", "employee"],
		as_list=True,
	):
		stale_entries_by_employee.setdefault(employee, []).append(working_time)

	for employee in stale_entries_by_employee:
		language = None
		user_id, prefered_email, first_name, reports_to = frappe.db.get_value(
			"Employee", employee, ["user_id", "prefered_email", "first_name", "reports_to"]
		)
		if user_id:
			language = frappe.db.get_value("User", user_id, "language")

		reply_to = frappe.db.get_value("Employee", reports_to, "prefered_email") if reports_to else None

		with print_language(language):
			frappe.sendmail(
				recipients=prefered_email or user_id,
				reply_to=reply_to,
				subject=_("Remember to submit your working time"),
				message=_(
					"""Dear {first_name},

One or more of your draft <a href='{url}'>working time entries</a> are older than {cutoff_days} days. Please submit them as soon as possible.

Thanks in advance!"""
				).format(
					first_name=first_name,
					url=get_url(f"/app/working-time?employee={employee}&docstatus=0"),
					cutoff_days=cutoff_days,
				),
			)
