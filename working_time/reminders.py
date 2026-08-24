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
		recipient = prefered_email or user_id
		if not recipient:
			continue
		if user_id:
			language = frappe.db.get_value("User", user_id, "language")

		reply_to = frappe.db.get_value("Employee", reports_to, "prefered_email") if reports_to else None

		with print_language(language):
			frappe.sendmail(
				recipients=recipient,
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
