from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_time, getdate

from working_time.permissions import get_user_employee, require_time_booking_identity


def _require_booking_access(issue: str):
	require_time_booking_identity()
	employee = get_user_employee()
	if not employee:
		frappe.throw(_("Your user account is not linked to an Employee record."), frappe.PermissionError)
	doc = _issue_with_read_access(issue)
	return employee, doc


def _task_with_read_access(task: str):
	doc = frappe.get_doc("Task", task)
	if not frappe.has_permission("Task", "read", doc=doc):
		frappe.throw(_("You are not permitted to read this task."), frappe.PermissionError)
	return doc


def _require_task_booking_access(task: str):
	require_time_booking_identity()
	employee = get_user_employee()
	if not employee:
		frappe.throw(_("Your user account is not linked to an Employee record."), frappe.PermissionError)
	task_doc = _task_with_read_access(task)
	if task_doc.status == "Cancelled":
		frappe.throw(_("Time cannot be booked to a cancelled task."))
	return employee, task_doc


def _issue_with_read_access(issue: str):
	doc = frappe.get_doc("Issue", issue)
	if not frappe.has_permission("Issue", "read", doc=doc):
		frappe.throw(_("You are not permitted to read this issue."), frappe.PermissionError)
	return doc


def validate_issue_booking(issue: str, project: str | None, task: str | None = None) -> None:
	require_time_booking_identity()
	issue_doc = _issue_with_read_access(issue)
	if not project:
		if task:
			frappe.throw(_("A task cannot be booked without a project."))
		return
	project_doc = frappe.get_doc("Project", project)
	if issue_doc.customer:
		if project_doc.customer != issue_doc.customer:
			frappe.throw(_("Issue and project must belong to the same customer."))
	elif project_doc.project_type != "Internal":
		frappe.throw(_("Internal issues may only be booked to Internal projects."))
	if task:
		task_state = frappe.db.get_value("Task", task, ["project", "issue"], as_dict=True)
		if not task_state or task_state.project != project:
			frappe.throw(_("The selected task does not belong to the project."))
		if task_state.issue and task_state.issue != issue_doc.name:
			frappe.throw(_("The selected task belongs to another issue."))


@frappe.whitelist()
def get_or_create_daily_working_time(employee: str, date: str):
	from working_time.permissions import require_employee_access

	employee = require_employee_access(employee)
	date = getdate(date)
	name = frappe.db.get_value("Working Time", {"employee": employee, "date": date, "docstatus": 0}, "name")
	if name:
		return frappe.get_doc("Working Time", name).as_dict()
	doc = frappe.get_doc({"doctype": "Working Time", "employee": employee, "date": date})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def get_issue_time_context(issue: str, date: str):
	employee, issue_doc = _require_booking_access(issue)
	filters = {"status": "Open"}
	if issue_doc.customer:
		filters["customer"] = issue_doc.customer
	else:
		filters["project_type"] = "Internal"
	projects = frappe.get_all(
		"Project",
		filters=filters,
		fields=["name", "project_name", "customer", "project_type", "billing_model"],
	)
	project = issue_doc.project
	if project and project not in {row.name for row in projects}:
		project = None
	if not project and len(projects) == 1:
		project = projects[0].name
	tasks = frappe.get_all(
		"Task",
		filters={"issue": issue_doc.name, "status": ("not in", ("Completed", "Cancelled"))},
		fields=["name", "project"],
		limit_page_length=2,
	)
	task = tasks[0].name if len(tasks) == 1 and tasks[0].project == project else None
	selected_project = next((row for row in projects if row.name == project), None)
	return {
		"issue": issue_doc.name,
		"employee": employee,
		"date": str(getdate(date)),
		"customer": issue_doc.customer,
		"projects": projects,
		"project": project,
		"task": task,
		"billable": int(bool(selected_project and selected_project.billing_model == "Time and Material")),
		"project_ambiguous": not project and len(projects) > 1,
	}


@frappe.whitelist()
def get_task_time_context(task: str, date: str):
	employee, task_doc = _require_task_booking_access(task)
	if not task_doc.project:
		frappe.throw(_("Link the task to a project before booking time."))
	project_doc = frappe.get_doc("Project", task_doc.project)
	if not frappe.has_permission("Project", "read", doc=project_doc):
		frappe.throw(_("You are not permitted to read this project."), frappe.PermissionError)
	if task_doc.issue:
		validate_issue_booking(task_doc.issue, task_doc.project, task_doc.name)
	return {
		"task": task_doc.name,
		"issue": task_doc.issue,
		"employee": employee,
		"date": str(getdate(date)),
		"customer": project_doc.customer,
		"project": project_doc.name,
		"billable": int(
			project_doc.project_type != "Internal" and project_doc.billing_model == "Time and Material"
		),
	}


def _append_time_log(
	*,
	employee: str,
	date: str,
	duration_minutes: int,
	project: str | None,
	task: str | None,
	issue: str | None,
	start_time: str | None,
	customer_description: str | None,
	internal_note: str | None,
	billable: int | str,
) -> dict[str, str]:
	duration_minutes = cint(duration_minutes)
	if duration_minutes <= 0:
		frappe.throw(_("Duration must be greater than zero."))
	working_time = get_or_create_daily_working_time(employee, date)
	doc = frappe.get_doc("Working Time", working_time.name)
	from_time = to_time = None
	if start_time:
		try:
			start = get_time(start_time)
		except (TypeError, ValueError):
			frappe.throw(_("Invalid start time."))
		start_datetime = datetime.combine(getdate(date), start)
		from_time = start.strftime("%H:%M:%S")
		to_time = (start_datetime + timedelta(minutes=duration_minutes)).time().strftime("%H:%M:%S")
	doc.append(
		"time_logs",
		{
			"duration": duration_minutes * 60,
			"from_time": from_time,
			"to_time": to_time,
			"project": project,
			"task": task,
			"issue": issue,
			"customer_description": customer_description,
			"internal_note": internal_note,
			"billable": "100%" if cint(billable) else "0%",
		},
	)
	doc.save()
	return {"working_time": doc.name, "route": f"/app/working-time/{doc.name}"}


@frappe.whitelist()
def add_issue_time(
	issue: str,
	date: str,
	duration_minutes: int,
	project: str | None = None,
	task: str | None = None,
	start_time: str | None = None,
	customer_description: str | None = None,
	internal_note: str | None = None,
	billable: int | str = 1,
):
	employee, issue_doc = _require_booking_access(issue)
	context = get_issue_time_context(issue_doc.name, date)
	project = project or context.get("project")
	task = task or (context.get("task") if project else None)
	validate_issue_booking(issue_doc.name, project, task)
	return _append_time_log(
		employee=employee,
		date=date,
		duration_minutes=duration_minutes,
		project=project,
		task=task,
		issue=issue_doc.name,
		start_time=start_time,
		customer_description=customer_description,
		internal_note=internal_note,
		billable=billable,
	)


@frappe.whitelist()
def add_task_time(
	task: str,
	date: str,
	duration_minutes: int,
	start_time: str | None = None,
	customer_description: str | None = None,
	internal_note: str | None = None,
	billable: int | str = 0,
):
	employee, task_doc = _require_task_booking_access(task)
	context = get_task_time_context(task_doc.name, date)
	return _append_time_log(
		employee=employee,
		date=date,
		duration_minutes=duration_minutes,
		project=context["project"],
		task=task_doc.name,
		issue=task_doc.issue,
		start_time=start_time,
		customer_description=customer_description,
		internal_note=internal_note,
		billable=billable,
	)
