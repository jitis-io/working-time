from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, get_time, getdate

from working_time.permissions import get_user_employee, require_time_booking_identity


def _target_ticket(ticket: str) -> str:
	doc = frappe.get_doc("HD Ticket", ticket)
	if doc.get("is_merged"):
		target = doc.get_merge_target()
		if not target:
			frappe.throw(_("The merged ticket has no valid target ticket."))
		return str(target)
	for fieldname in ("merged_into", "merged_with", "merged_ticket"):
		if doc.meta.has_field(fieldname) and doc.get(fieldname):
			return str(doc.get(fieldname))
	return doc.name


def _ticket_customer(ticket_doc) -> str | None:
	if not ticket_doc.customer:
		return None
	customers = frappe.get_all(
		"HD Customer", filters={"name": ticket_doc.customer}, fields=["erpnext_customer"], limit=2
	)
	if len(customers) != 1 or not customers[0].erpnext_customer:
		frappe.throw(_("The ticket customer has no unique ERPNext customer mapping."))
	return customers[0].erpnext_customer


def _require_booking_access(ticket: str):
	require_time_booking_identity()
	employee = get_user_employee()
	if not employee:
		frappe.throw(_("Your user account is not linked to an Employee record."), frappe.PermissionError)
	doc = _ticket_with_read_access(ticket)
	return employee, doc


def _ticket_with_read_access(ticket: str):
	ticket = _target_ticket(ticket)
	doc = frappe.get_doc("HD Ticket", ticket)
	if not frappe.has_permission("HD Ticket", "read", doc=doc):
		frappe.throw(_("You are not permitted to read this ticket."), frappe.PermissionError)
	return doc


def validate_ticket_booking(ticket: str, project: str | None, task: str | None = None) -> None:
	require_time_booking_identity()
	ticket_doc = _ticket_with_read_access(ticket)
	customer = _ticket_customer(ticket_doc)
	if not project:
		if task:
			frappe.throw(_("A task cannot be booked without a project."))
		return
	project_doc = frappe.get_doc("Project", project)
	if customer:
		if project_doc.customer != customer:
			frappe.throw(_("Ticket and project must belong to the same customer."))
	elif project_doc.project_type != "Internal":
		frappe.throw(_("Internal tickets may only be booked to Internal projects."))
	if task and frappe.db.get_value("Task", task, "project") != project:
		frappe.throw(_("The selected task does not belong to the project."))


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
def get_ticket_time_context(ticket: str, date: str):
	employee, ticket_doc = _require_booking_access(ticket)
	customer = _ticket_customer(ticket_doc)
	filters = {"status": "Open"}
	if customer:
		filters["customer"] = customer
	else:
		filters["project_type"] = "Internal"
	projects = frappe.get_all(
		"Project",
		filters=filters,
		fields=["name", "project_name", "customer", "project_type", "billing_model"],
	)
	project = ticket_doc.get("erpnext_project")
	if project and project not in {row.name for row in projects}:
		project = None
	if not project and len(projects) == 1:
		project = projects[0].name
	return {
		"ticket": ticket_doc.name,
		"employee": employee,
		"date": str(getdate(date)),
		"customer": customer,
		"projects": projects,
		"project": project,
		"task": ticket_doc.get("erpnext_task") if project else None,
		"project_ambiguous": not project and len(projects) > 1,
	}


@frappe.whitelist()
def add_ticket_time(
	ticket: str,
	date: str,
	duration_minutes: int,
	project: str | None = None,
	task: str | None = None,
	start_time: str | None = None,
	customer_description: str | None = None,
	internal_note: str | None = None,
	billable: int | str = 1,
):
	employee, ticket_doc = _require_booking_access(ticket)
	duration_minutes = cint(duration_minutes)
	if duration_minutes <= 0:
		frappe.throw(_("Duration must be greater than zero."))
	context = get_ticket_time_context(ticket_doc.name, date)
	project = project or context.get("project")
	task = task or (context.get("task") if project else None)
	validate_ticket_booking(ticket_doc.name, project, task)
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
			"helpdesk_ticket": ticket_doc.name,
			"customer_description": customer_description,
			"internal_note": internal_note,
			"billable": "100%" if cint(billable) else "0%",
		},
	)
	doc.save()
	return {"working_time": doc.name, "route": f"/app/working-time/{doc.name}"}
