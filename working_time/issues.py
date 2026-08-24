from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_time, getdate

from working_time.permissions import get_user_employee, require_time_booking_identity


def _project_time_is_billable(project_doc) -> bool:
	getter = getattr(project_doc, "get", None)
	project_type = getter("project_type") if callable(getter) else getattr(project_doc, "project_type", None)
	time_billable = getter("time_billable") if callable(getter) else getattr(project_doc, "time_billable", 0)
	return project_type != "Internal" and bool(cint(time_billable))


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
	if not frappe.has_permission("Project", "read", doc=project_doc):
		frappe.throw(_("You are not permitted to read this project."), frappe.PermissionError)
	if issue_doc.project and issue_doc.project != project:
		frappe.throw(_("The issue is linked to another project."))
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


@frappe.whitelist(methods=["POST"])
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


@frappe.whitelist(methods=["POST"])
def get_or_create_my_working_time(date: str):
	require_time_booking_identity()
	employee = get_user_employee()
	if not employee:
		frappe.throw(_("Your user account is not linked to an Employee record."), frappe.PermissionError)
	return get_or_create_daily_working_time(employee, date)


@frappe.whitelist()
def get_issue_time_context(issue: str, date: str):
	employee, issue_doc = _require_booking_access(issue)
	project = issue_doc.project
	if not project and issue_doc.customer:
		project = frappe.db.get_value("Customer", issue_doc.customer, "customer_project")
	if not project:
		frappe.throw(_("Link the issue to its customer project before booking time."))
	project_doc = frappe.get_doc("Project", project)
	if not frappe.has_permission("Project", "read", doc=project_doc):
		frappe.throw(_("You are not permitted to read this project."), frappe.PermissionError)
	validate_issue_booking(issue_doc.name, project)
	try:
		tasks = frappe.get_list(
			"Task",
			filters={"issue": issue_doc.name, "status": ("not in", ("Completed", "Cancelled"))},
			fields=["name", "project"],
			limit_page_length=2,
		)
	except frappe.PermissionError:
		tasks = []
	task = tasks[0].name if len(tasks) == 1 and tasks[0].project == project else None
	return {
		"issue": issue_doc.name,
		"employee": employee,
		"date": str(getdate(date)),
		"customer": issue_doc.customer,
		"project": project,
		"project_name": project_doc.project_name,
		"task": task,
		"billable": int(_project_time_is_billable(project_doc)),
		"time_billable": int(_project_time_is_billable(project_doc)),
		"project_ambiguous": False,
	}


@frappe.whitelist()
def get_project_time_context(project: str, date: str):
	require_time_booking_identity()
	employee = get_user_employee()
	if not employee:
		frappe.throw(_("Your user account is not linked to an Employee record."), frappe.PermissionError)
	project_doc = frappe.get_doc("Project", project)
	if not frappe.has_permission("Project", "read", doc=project_doc):
		frappe.throw(_("You are not permitted to read this project."), frappe.PermissionError)
	if project_doc.status in {"Completed", "Cancelled"} or project_doc.is_active == "No":
		frappe.throw(_("Time can only be booked to an open project."))
	return {
		"employee": employee,
		"date": str(getdate(date)),
		"customer": project_doc.customer,
		"project": project_doc.name,
		"project_name": project_doc.project_name,
		"billable": int(_project_time_is_billable(project_doc)),
		"time_billable": int(_project_time_is_billable(project_doc)),
	}


@frappe.whitelist()
def get_time_booking_context(
	date: str, project: str | None = None, issue: str | None = None, task: str | None = None
):
	if task:
		context = get_task_time_context(task, date)
	elif issue:
		context = get_issue_time_context(issue, date)
	elif project:
		context = get_project_time_context(project, date)
	else:
		frappe.throw(_("Select a project, issue or task before booking time."))

	resolved_project = context["project"]
	if project and project != resolved_project:
		frappe.throw(_("The selected work item belongs to another project."))
	project_doc = frappe.get_doc("Project", resolved_project)
	issues = frappe.get_list(
		"Issue",
		filters={"project": resolved_project, "status": ("not in", ("Resolved", "Closed"))},
		fields=["name", "subject"],
		order_by="modified desc",
		limit_page_length=100,
	)
	tasks = frappe.get_list(
		"Task",
		filters={"project": resolved_project, "status": ("not in", ("Completed", "Cancelled"))},
		fields=["name", "subject", "issue"],
		order_by="modified desc",
		limit_page_length=100,
	)
	return {
		**context,
		"project": resolved_project,
		"project_name": project_doc.project_name,
		"issue": issue or context.get("issue"),
		"task": task or context.get("task"),
		"issues": issues,
		"tasks": tasks,
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
		"billable": int(_project_time_is_billable(project_doc)),
		"time_billable": int(_project_time_is_billable(project_doc)),
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


@frappe.whitelist(methods=["POST"])
def book_time(
	project: str,
	date: str,
	duration_minutes: int,
	task: str | None = None,
	issue: str | None = None,
	start_time: str | None = None,
	customer_description: str | None = None,
	internal_note: str | None = None,
	billable: int | str = 0,
):
	context = get_time_booking_context(date=date, project=project, issue=issue, task=task)
	resolved_issue = context.get("issue")
	resolved_task = context.get("task")
	if resolved_task:
		task_doc = _task_with_read_access(resolved_task)
		if task_doc.project != project:
			frappe.throw(_("The selected task belongs to another project."))
		if resolved_issue and task_doc.issue and task_doc.issue != resolved_issue:
			frappe.throw(_("The selected task belongs to another issue."))
		resolved_issue = resolved_issue or task_doc.issue
	if resolved_issue:
		validate_issue_booking(resolved_issue, project, resolved_task)
	return _append_time_log(
		employee=context["employee"],
		date=date,
		duration_minutes=duration_minutes,
		project=project,
		task=resolved_task,
		issue=resolved_issue,
		start_time=start_time,
		customer_description=customer_description,
		internal_note=internal_note,
		billable=billable,
	)


@frappe.whitelist(methods=["POST"])
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


@frappe.whitelist(methods=["POST"])
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
