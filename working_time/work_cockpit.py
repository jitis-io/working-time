from __future__ import annotations

import html
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from working_time.permissions import (
	get_user_employee,
	is_system_manager,
	require_time_booking_identity,
)
from working_time.platform_operations import (
	_billing_source_references,
	_billing_status,
	_claimed_billing_sources,
)

OPEN_ISSUE_STATUSES = ("Open", "Replied", "On Hold")
OPEN_TASK_STATUSES = ("Open", "Working", "Pending Review", "Overdue")
OPERATIONAL_STATES = ("Normal", "Blockiert", "Wartet auf Kunde")
UNBILLED_STATUSES = ("Eligible", "Missing Project", "Missing Customer", "Missing Sales Order", "Locked")
VALID_VIEWS = ("today", "blocked", "waiting_customer", "unbilled", "all")
VALID_SCOPES = ("mine", "team")
MAX_NATIVE_ITEMS = 500
MAX_EXTERNAL_ITEMS = 500
MAX_DESCRIPTION_LENGTH = 4000
TASK_PRIORITIES = ("Low", "Medium", "High", "Urgent")


def _assigned_filters(statuses: tuple[str, ...], user: str, scope: str = "mine") -> dict[str, Any]:
	filters: dict[str, Any] = {"status": ["in", list(statuses)]}
	if scope == "mine" or not is_system_manager(user):
		# _assign is maintained by Frappe as a JSON array. Matching the quoted
		# identity avoids collisions between similarly named users. Escape SQL
		# LIKE metacharacters in otherwise valid User IDs such as `first_last`.
		encoded_user = json.dumps(user, ensure_ascii=False)
		encoded_user = encoded_user.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
		filters["_assign"] = ["like", f"%{encoded_user}%"]
	return filters


def _parse_assignments(value: str | list[str] | None) -> list[str]:
	if isinstance(value, list):
		return [str(user) for user in value]
	if not value:
		return []
	try:
		parsed = json.loads(value)
	except (TypeError, ValueError):
		return []
	return [str(user) for user in parsed] if isinstance(parsed, list) else []


def _bounded_description(value: Any) -> str:
	return str(value or "")[:MAX_DESCRIPTION_LENGTH]


def _date_string(value: Any) -> str | None:
	if not value:
		return None
	try:
		return str(getdate(value))
	except (TypeError, ValueError):
		return None


def _permission_aware_list(doctype: str, **kwargs: Any) -> list[Any]:
	try:
		return frappe.get_list(doctype, **kwargs)
	except frappe.PermissionError:
		return []


def _get_native_items(user: str, scope: str = "mine") -> list[dict[str, Any]]:
	issues = _permission_aware_list(
		"Issue",
		filters=_assigned_filters(OPEN_ISSUE_STATUSES, user, scope),
		fields=[
			"name",
			"subject",
			"description",
			"customer",
			"project",
			"priority",
			"status",
			"working_time_operational_state",
			"working_time_planned_date",
			"opening_date",
			"_assign",
		],
		order_by="working_time_planned_date asc, modified desc",
		limit_page_length=MAX_NATIVE_ITEMS,
	)
	tasks = _permission_aware_list(
		"Task",
		filters=_assigned_filters(OPEN_TASK_STATUSES, user, scope),
		fields=[
			"name",
			"subject",
			"description",
			"project",
			"issue",
			"priority",
			"status",
			"working_time_operational_state",
			"exp_start_date",
			"exp_end_date",
			"_assign",
		],
		order_by="exp_end_date asc, modified desc",
		limit_page_length=MAX_NATIVE_ITEMS,
	)
	project_names = {row.project for row in [*issues, *tasks] if row.get("project")}
	projects = _project_context(project_names)
	items: list[dict[str, Any]] = []
	for issue in issues:
		project = projects.get(issue.project, {})
		items.append(
			{
				"source": "erpnext",
				"item_type": "Issue",
				"name": issue.name,
				"title": issue.subject,
				"description": _bounded_description(issue.description),
				"status": issue.status,
				"priority": issue.priority,
				"customer": issue.customer or project.get("customer"),
				"project": issue.project,
				"project_name": project.get("project_name"),
				"due_date": _date_string(issue.working_time_planned_date),
				"operational_state": issue.working_time_operational_state or "Normal",
				"assigned_to": _parse_assignments(issue.get("_assign")),
				"route": f"/app/issue/{issue.name}",
				"can_promote": True,
				"actual_hours": 0.0,
				"worked_today": False,
				"billing_statuses": [],
				"unbilled": False,
				"commercial_context": project,
			}
		)
	for task in tasks:
		project = projects.get(task.project, {})
		items.append(
			{
				"source": "erpnext",
				"item_type": "Task",
				"name": task.name,
				"title": task.subject,
				"description": _bounded_description(task.description),
				"status": task.status,
				"priority": task.priority,
				"customer": project.get("customer"),
				"project": task.project,
				"project_name": project.get("project_name"),
				"issue": task.issue,
				"due_date": _date_string(task.exp_end_date or task.exp_start_date),
				"operational_state": task.working_time_operational_state or "Normal",
				"assigned_to": _parse_assignments(task.get("_assign")),
				"route": f"/app/task/{task.name}",
				"can_promote": False,
				"actual_hours": 0.0,
				"worked_today": False,
				"billing_statuses": [],
				"unbilled": False,
				"commercial_context": project,
			}
		)
	_apply_time_and_billing_context(items)
	return items


def _visible_links(doctype: str, names: set[str]) -> set[str]:
	if not names:
		return set()
	return {
		row.name
		for row in _permission_aware_list(
			doctype,
			filters={"name": ["in", sorted(names)]},
			fields=["name"],
			limit_page_length=0,
		)
	}


def _project_context(project_names: set[str]) -> dict[str, dict[str, Any]]:
	if not project_names:
		return {}
	rows = _permission_aware_list(
		"Project",
		filters={"name": ["in", sorted(project_names)]},
		fields=["name", "project_name", "customer", "contract", "sales_order"],
		limit_page_length=0,
	)
	visible_contracts = _visible_links("Contract", {row.contract for row in rows if row.contract})
	visible_orders = _visible_links("Sales Order", {row.sales_order for row in rows if row.sales_order})
	return {
		row.name: {
			"project_name": row.project_name,
			"customer": row.customer,
			"contract": row.contract if row.contract in visible_contracts else None,
			"sales_order": row.sales_order if row.sales_order in visible_orders else None,
			"sales_invoices": [],
		}
		for row in rows
	}


def _relevant_timesheet_details(items: list[dict[str, Any]]) -> list[Any]:
	task_names = {item["name"] for item in items if item["item_type"] == "Task"}
	issue_names = {item["name"] for item in items if item["item_type"] == "Issue"}
	fields = [
		"name",
		"parent",
		"project",
		"task",
		"issue",
		"hours",
		"billing_hours",
		"is_billable",
		"from_time",
		"sales_invoice",
	]
	rows: dict[str, Any] = {}
	if task_names:
		for row in frappe.get_all(
			"Timesheet Detail",
			filters={"task": ["in", sorted(task_names)], "docstatus": 1},
			fields=fields,
		):
			rows[row.name] = row
	if issue_names:
		for row in frappe.get_all(
			"Timesheet Detail",
			filters={"issue": ["in", sorted(issue_names)], "docstatus": 1},
			fields=fields,
		):
			rows[row.name] = row
	if not rows:
		return []
	visible_timesheets = _visible_links("Timesheet", {row.parent for row in rows.values()})
	return [row for row in rows.values() if row.parent in visible_timesheets]


def _review_invoice_links(project_names: set[str], detail_names: set[str]) -> dict[str, set[str]]:
	result = {name: set() for name in detail_names}
	if not project_names or not detail_names:
		return result
	for item in frappe.get_all(
		"Billing Review Item",
		filters={"project": ["in", sorted(project_names)], "sales_invoice": ["is", "set"]},
		fields=["sales_invoice", "timesheet_detail", "source_details_json"],
	):
		for detail_name in _billing_source_references(item):
			if detail_name in result and item.sales_invoice:
				result[detail_name].add(item.sales_invoice)
	return result


def _apply_time_and_billing_context(items: list[dict[str, Any]]) -> None:
	by_key = {(item["item_type"], item["name"]): item for item in items}
	details = _relevant_timesheet_details(items)
	if not details:
		return
	claimed = _claimed_billing_sources()
	project_names = {row.project for row in details if row.project}
	review_invoices = _review_invoice_links(project_names, {row.name for row in details})
	all_invoice_names = {
		invoice
		for row in details
		for invoice in ([row.sales_invoice] if row.sales_invoice else []) + list(review_invoices[row.name])
	}
	visible_invoices = _visible_links("Sales Invoice", all_invoice_names)
	today = getdate(nowdate())
	for detail in details:
		key = (
			("Task", detail.task)
			if detail.task and ("Task", detail.task) in by_key
			else ("Issue", detail.issue)
		)
		item = by_key.get(key)
		if not item:
			continue
		item["actual_hours"] = flt(item["actual_hours"]) + flt(detail.hours)
		if detail.from_time and getdate(detail.from_time) == today:
			item["worked_today"] = True
		billing_hours = detail.billing_hours
		if billing_hours is None:
			billing_hours = detail.hours if cint(detail.is_billable) else 0
		if flt(billing_hours) > 0:
			# Missing Project is visible from the work item itself. Other billing
			# states are only calculated when the Project passed native read checks.
			if not detail.project or item["commercial_context"]:
				if detail.sales_invoice:
					status = "Already Invoiced"
				else:
					status, _context = _billing_status(detail, claimed)
				if status not in item["billing_statuses"]:
					item["billing_statuses"].append(status)
				if status in UNBILLED_STATUSES:
					item["unbilled"] = True
		invoice_names = ({detail.sales_invoice} if detail.sales_invoice else set()) | review_invoices[
			detail.name
		]
		project_context = item["commercial_context"]
		project_context.setdefault("sales_invoices", [])
		for invoice in sorted(invoice_names & visible_invoices):
			if invoice not in project_context["sales_invoices"]:
				project_context["sales_invoices"].append(invoice)


def _filter_view(items: list[dict[str, Any]], view: str) -> list[dict[str, Any]]:
	if view == "all":
		return items
	if view == "blocked":
		return [item for item in items if item.get("operational_state") == "Blockiert"]
	if view == "waiting_customer":
		return [item for item in items if item.get("operational_state") == "Wartet auf Kunde"]
	if view == "unbilled":
		return [item for item in items if item.get("unbilled")]
	today = getdate(nowdate())
	return [
		item
		for item in items
		if item.get("worked_today")
		or item.get("status") == "Working"
		or (item.get("due_date") and getdate(item["due_date"]) <= today)
	]


def _provider_functions() -> list[Callable[..., Any]]:
	providers: list[Callable[..., Any]] = []
	for dotted_path in frappe.get_hooks("work_cockpit_providers") or []:
		try:
			provider = frappe.get_attr(dotted_path)
			if not callable(provider):
				raise TypeError(f"Hook is not callable: {dotted_path}")
			providers.append(provider)
		except Exception:
			frappe.log_error(title=f"Work Cockpit provider could not be loaded: {dotted_path}")
	return providers


def _normalize_external_item(value: Any, provider: str) -> dict[str, Any] | None:
	if not isinstance(value, dict) or not value.get("external_id") or not value.get("title"):
		return None
	state = {
		"Blocked": "Blockiert",
		"Waiting for Customer": "Wartet auf Kunde",
	}.get(value.get("operational_state"), value.get("operational_state") or "Normal")
	if state not in OPERATIONAL_STATES:
		state = "Normal"
	due_date = value.get("due_date")
	if due_date:
		try:
			due_date = str(getdate(due_date))
		except (TypeError, ValueError):
			due_date = None
	assigned_to = value.get("assigned_to") or []
	if isinstance(assigned_to, str):
		assigned_to = [assigned_to]
	elif not isinstance(assigned_to, (list, tuple, set)):
		assigned_to = []
	billing_statuses = value.get("billing_statuses") or []
	if isinstance(billing_statuses, str):
		billing_statuses = [billing_statuses]
	elif not isinstance(billing_statuses, (list, tuple, set)):
		billing_statuses = []
	promotion_method = value.get("promotion_method")
	if not isinstance(promotion_method, str):
		promotion_method = None
	promotion_args = value.get("promotion_args")
	if not isinstance(promotion_args, dict):
		promotion_args = {}
	commercial_context = value.get("commercial_context")
	if not isinstance(commercial_context, dict):
		commercial_context = {}
	invoice_names = commercial_context.get("sales_invoices") or []
	if isinstance(invoice_names, str):
		invoice_names = [invoice_names]
	elif not isinstance(invoice_names, (list, tuple, set)):
		invoice_names = []
	commercial_context = {
		"contract": str(commercial_context["contract"]) if commercial_context.get("contract") else None,
		"sales_order": (
			str(commercial_context["sales_order"]) if commercial_context.get("sales_order") else None
		),
		"sales_invoices": [str(name) for name in invoice_names],
	}
	route = str(value["route"]) if value.get("route") else None
	if route and not route.startswith("/"):
		parsed_route = urlparse(route)
		if parsed_route.scheme != "https" or not parsed_route.netloc:
			route = None
	return {
		"source": str(value.get("source") or provider),
		"item_type": "External",
		"name": str(value["external_id"]),
		"title": str(value["title"]),
		"description": _bounded_description(value.get("description")),
		"description_is_plain_text": True,
		"status": str(value.get("status") or "Open"),
		"priority": str(value["priority"]) if value.get("priority") else None,
		"customer": str(value["customer"]) if value.get("customer") else None,
		"project": str(value["project"]) if value.get("project") else None,
		"project_name": str(value["project_name"]) if value.get("project_name") else None,
		"due_date": due_date,
		"operational_state": state,
		"assigned_to": [str(user) for user in assigned_to],
		"is_personal": value.get("is_personal") is True,
		"route": route,
		"can_promote": bool(promotion_method),
		"promotion_method": promotion_method,
		"promotion_args": promotion_args,
		"actual_hours": flt(value.get("actual_hours")),
		"worked_today": bool(value.get("worked_today")),
		"billing_statuses": [str(status) for status in billing_statuses],
		"unbilled": bool(value.get("unbilled")),
		"commercial_context": commercial_context,
	}


def _get_external_items(view: str, user: str) -> tuple[list[dict[str, Any]], list[str]]:
	items: list[dict[str, Any]] = []
	errors: list[str] = []
	for provider in _provider_functions():
		provider_name = f"{provider.__module__}.{provider.__name__}"
		try:
			values = list(provider(view=view, user=user) or [])
			for value in values[:MAX_EXTERNAL_ITEMS]:
				item = _normalize_external_item(value, provider_name)
				if item:
					items.append(item)
		except Exception:
			errors.append(provider_name)
			frappe.log_error(frappe.get_traceback(), f"Work Cockpit provider failed: {provider_name}")
	return items, errors


@frappe.whitelist()
def get_work_cockpit(view: str = "today", scope: str = "mine") -> dict[str, Any]:
	if view not in VALID_VIEWS:
		frappe.throw(_("Invalid Work Cockpit view."))
	if scope not in VALID_SCOPES:
		frappe.throw(_("Invalid Work Cockpit scope."))
	user = require_time_booking_identity()
	if scope == "team" and not is_system_manager(user):
		frappe.throw(_("Only System Managers may open the team scope."), frappe.PermissionError)
	native_items = _filter_view(_get_native_items(user, scope), view)
	external_items, provider_errors = _get_external_items(view, user)
	if scope == "mine":
		external_items = [item for item in external_items if item.get("is_personal")]
	items = [*native_items, *_filter_view(external_items, view)]
	items.sort(key=lambda item: (str(item.get("due_date") or "9999-12-31"), item["title"].lower()))
	capabilities = {
		"can_create_task": bool(frappe.has_permission("Task", "create")),
		"can_update_task": bool(frappe.has_permission("Task", "write")),
		"can_book_time": bool(get_user_employee(user))
		and bool(frappe.has_permission("Working Time", "create")),
	}
	return {
		"view": view,
		"scope": scope,
		"can_view_team": is_system_manager(user),
		"capabilities": capabilities,
		"items": items,
		"provider_errors": provider_errors,
		"counts": {
			"issues": sum(item["item_type"] == "Issue" for item in items),
			"tasks": sum(item["item_type"] == "Task" for item in items),
			"external": sum(item["item_type"] == "External" for item in items),
		},
	}


def _quick_task_projects() -> list[Any]:
	return _permission_aware_list(
		"Project",
		filters={"status": "Open"},
		fields=["name", "project_name", "customer", "project_type"],
		order_by="project_type desc, project_name asc",
		limit_page_length=MAX_NATIVE_ITEMS,
	)


@frappe.whitelist()
def get_quick_task_context() -> dict[str, Any]:
	require_time_booking_identity()
	if not frappe.has_permission("Task", "create"):
		frappe.throw(_("You are not permitted to create tasks."), frappe.PermissionError)
	projects = _quick_task_projects()
	internal_projects = [project for project in projects if project.project_type == "Internal"]
	default_project = internal_projects[0].name if len(internal_projects) == 1 else None
	if not default_project and len(projects) == 1:
		default_project = projects[0].name
	return {
		"default_project": default_project,
		"projects": [
			{
				"name": project.name,
				"project_name": project.project_name,
				"customer": project.customer,
				"project_type": project.project_type,
			}
			for project in projects
		],
	}


def _safe_task_description(value: str | None) -> str | None:
	value = str(value or "").strip()
	if not value:
		return None
	return f"<p>{html.escape(value).replace(chr(10), '<br>')}</p>"


@frappe.whitelist()
def create_quick_task(
	subject: str,
	project: str,
	description: str | None = None,
	due_date: str | None = None,
	priority: str = "Medium",
) -> dict[str, Any]:
	user = require_time_booking_identity()
	if not frappe.has_permission("Task", "create"):
		frappe.throw(_("You are not permitted to create tasks."), frappe.PermissionError)
	subject = str(subject or "").strip()
	if not subject:
		frappe.throw(_("Enter a task title."))
	if len(subject) > 140:
		frappe.throw(_("Task titles may contain at most 140 characters."))
	if priority not in TASK_PRIORITIES:
		frappe.throw(_("Invalid task priority."))
	project = str(project or "").strip()
	if not project:
		frappe.throw(_("Select an open project."))
	project_doc = frappe.get_doc("Project", project)
	if not frappe.has_permission("Project", "read", doc=project_doc):
		frappe.throw(_("You are not permitted to use this project."), frappe.PermissionError)
	if project_doc.status != "Open":
		frappe.throw(_("Select an open project."))
	task_values: dict[str, Any] = {
		"doctype": "Task",
		"subject": subject,
		"description": _safe_task_description(description),
		"project": project_doc.name,
		"priority": priority,
		"status": "Open",
	}
	if due_date:
		try:
			task_values["exp_end_date"] = str(getdate(due_date))
		except (TypeError, ValueError):
			frappe.throw(_("Invalid due date."))
	task = frappe.get_doc(task_values).insert()
	from frappe.desk.form.assign_to import add as assign_to

	assign_to(
		{
			"assign_to": [user],
			"doctype": "Task",
			"name": task.name,
			"description": task.subject,
			"priority": task.priority,
		}
	)
	return {"name": task.name, "route": f"/app/task/{task.name}", "created": True}


@frappe.whitelist()
def complete_task(task: str) -> dict[str, Any]:
	user = require_time_booking_identity()
	task_doc = frappe.get_doc("Task", task)
	if not frappe.has_permission("Task", "write", doc=task_doc):
		frappe.throw(_("You are not permitted to update this task."), frappe.PermissionError)
	if task_doc.status == "Cancelled":
		frappe.throw(_("A cancelled task cannot be completed."))
	if task_doc.status == "Completed":
		return {"name": task_doc.name, "status": task_doc.status, "changed": False}
	completed_on = nowdate()
	task_doc.completed_on = completed_on
	task_doc.completed_by = user
	task_doc.closing_date = completed_on
	if task_doc.project and frappe.db.get_value("Project", task_doc.project, "project_type") == "Internal":
		# Internal Projects are durable backlog containers. ERPNext normally closes
		# a Project when its last Task is completed, which would make the one-project
		# internal workflow unusable until someone manually reopens it.
		task_doc.flags.from_project = True
	task_doc.status = "Completed"
	task_doc.save()
	return {"name": task_doc.name, "status": task_doc.status, "changed": True}


def _issue_with_read_access(issue: str):
	doc = frappe.get_doc("Issue", issue)
	if not frappe.has_permission("Issue", "read", doc=doc):
		frappe.throw(_("You are not permitted to read this issue."), frappe.PermissionError)
	return doc


def _promotion_projects(issue_doc: Any) -> list[Any]:
	filters: dict[str, Any] = {"status": "Open"}
	if issue_doc.customer:
		filters["customer"] = issue_doc.customer
	else:
		filters["project_type"] = "Internal"
	return frappe.get_list(
		"Project",
		filters=filters,
		fields=["name", "project_name", "customer", "project_type"],
		order_by="project_name asc",
		limit_page_length=0,
	)


@frappe.whitelist()
def get_issue_promotion_context(issue: str) -> dict[str, Any]:
	require_time_booking_identity()
	issue_doc = _issue_with_read_access(issue)
	projects = _promotion_projects(issue_doc)
	selected = issue_doc.project if issue_doc.project in {row.name for row in projects} else None
	return {"issue": issue_doc.name, "project": selected, "projects": projects}


def _task_priority(issue_priority: str | None) -> str:
	value = (issue_priority or "").strip().lower()
	return {"low": "Low", "medium": "Medium", "high": "High", "urgent": "Urgent"}.get(value, "Medium")


@frappe.whitelist()
def promote_issue_to_task(issue: str, project: str | None = None) -> dict[str, Any]:
	user = require_time_booking_identity()
	if not frappe.has_permission("Task", "create"):
		frappe.throw(_("You are not permitted to create tasks."), frappe.PermissionError)
	_issue_with_read_access(issue)
	# Serialize promotion for this Issue. The Task.issue lookup alone is not a
	# unique database constraint and therefore cannot prevent concurrent clicks.
	frappe.db.sql("select name from `tabIssue` where name=%s for update", (issue,))
	issue_doc = _issue_with_read_access(issue)
	status_placeholders = ", ".join(["%s"] * len(OPEN_TASK_STATUSES))
	existing_rows = frappe.db.sql(
		f"""select name
		from `tabTask`
		where issue=%s and status in ({status_placeholders})
		order by creation asc
		limit 1 for update""",
		(issue_doc.name, *OPEN_TASK_STATUSES),
		as_dict=True,
	)
	existing = existing_rows[0].name if existing_rows else None
	if existing:
		task_doc = frappe.get_doc("Task", existing)
		if not frappe.has_permission("Task", "read", doc=task_doc):
			frappe.throw(_("An open task already exists for this issue."), frappe.PermissionError)
		return {"name": existing, "route": f"/app/task/{existing}", "created": False}
	project = project or issue_doc.project
	projects = {row.name: row for row in _promotion_projects(issue_doc)}
	if not project:
		frappe.throw(_("Select an open project before creating the task."))
	if issue_doc.project and project != issue_doc.project:
		frappe.throw(_("The task must use the project already linked to this issue."))
	if project not in projects:
		frappe.throw(_("The selected project is not available for this issue."), frappe.PermissionError)
	task = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": issue_doc.subject,
			"description": issue_doc.description,
			"project": project,
			"issue": issue_doc.name,
			"priority": _task_priority(issue_doc.priority),
			"working_time_operational_state": issue_doc.working_time_operational_state or "Normal",
		}
	)
	task.insert()
	from frappe.desk.form.assign_to import add as assign_to

	assign_to(
		{
			"assign_to": [user],
			"doctype": "Task",
			"name": task.name,
			"description": task.subject,
			"priority": task.priority,
		}
	)
	return {"name": task.name, "route": f"/app/task/{task.name}", "created": True}


@frappe.whitelist()
def get_issue_attachments(task: str) -> list[dict[str, Any]]:
	require_time_booking_identity()
	task_doc = frappe.get_doc("Task", task)
	if not frappe.has_permission("Task", "read", doc=task_doc):
		frappe.throw(_("You are not permitted to read this task."), frappe.PermissionError)
	if not task_doc.issue:
		return []
	_issue_with_read_access(task_doc.issue)
	return frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Issue",
			"attached_to_name": task_doc.issue,
			"is_private": 1,
		},
		fields=["name", "file_name", "file_url", "file_size"],
		order_by="creation asc",
	)


@frappe.whitelist()
def get_project_commercial_context(project: str) -> dict[str, Any]:
	require_time_booking_identity()
	project_doc = frappe.get_doc("Project", project)
	if not frappe.has_permission("Project", "read", doc=project_doc):
		frappe.throw(_("You are not permitted to read this project."), frappe.PermissionError)
	context = _project_context({project}).get(project, {})
	invoices = {
		row.sales_invoice
		for row in frappe.get_all(
			"Timesheet Detail",
			filters={"project": project, "sales_invoice": ["is", "set"], "docstatus": 1},
			fields=["sales_invoice"],
		)
		if row.sales_invoice
	}
	invoices.update(
		row.sales_invoice
		for row in frappe.get_all(
			"Billing Review Item",
			filters={"project": project, "sales_invoice": ["is", "set"]},
			fields=["sales_invoice"],
		)
		if row.sales_invoice
	)
	context["sales_invoices"] = sorted(_visible_links("Sales Invoice", invoices))
	return context
