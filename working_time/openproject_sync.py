from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import frappe
from frappe import _

from .openproject_client import OpenProjectClient
from .openproject_utils import get_openproject_work_package_url

SYNC_QUEUE = "long"
SYNC_TIMEOUT = 600
SYNC_OVERLAP = timedelta(minutes=5)
OPENPROJECT_WEBHOOK_ACTIONS = {
	"project:created",
	"project:updated",
	"work_package:created",
	"work_package:updated",
	"work_package:deleted",
	"time_entry:created",
	"time_entry:updated",
	"time_entry:deleted",
}


def _normalize_id(value: Any) -> str | None:
	if value is None:
		return None
	text = str(value).strip()
	return text or None


def _extract_id(href: str | None) -> str | None:
	if not href:
		return None
	return href.rstrip("/").split("/")[-1] or None


def _parse_formattable(value: Any) -> str:
	if isinstance(value, dict):
		return str(value.get("raw") or value.get("html") or "")
	return str(value or "")


def _parse_duration(value: str | float | int | None) -> float:
	if value is None:
		return 0.0
	if isinstance(value, int | float):
		return float(value)

	text = str(value).upper()
	if not text.startswith("P"):
		try:
			return float(text)
		except ValueError:
			return 0.0

	import re

	match = re.match(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", text)
	if not match:
		return 0.0

	days, hours, minutes, seconds = (int(match.group(index) or 0) for index in range(1, 5))
	return days * 24.0 + hours + minutes / 60.0 + seconds / 3600.0


def _parse_op_datetime_value(value: str | None) -> datetime | None:
	if not value:
		return None
	try:
		dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
		if dt.tzinfo is None:
			return dt.replace(tzinfo=UTC)
		return dt.astimezone(UTC)
	except Exception:
		return None


def _parse_op_datetime(value: str | None) -> str | None:
	dt = _parse_op_datetime_value(value)
	if not dt:
		return None
	return dt.astimezone().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _format_op_datetime(value: datetime) -> str:
	return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _site_name(openproject_site: str | None = None) -> str:
	if openproject_site:
		return openproject_site

	sites = frappe.get_all("OpenProject Site", pluck="name")
	if not sites:
		frappe.throw(_("No OpenProject Site configured"))
	if len(sites) > 1:
		frappe.throw(_("Only one OpenProject Site is supported"))
	return sites[0]


def _timesheet_covers_date(timesheet: Any, spent_on: str) -> bool:
	return str(timesheet.start_date) <= spent_on <= str(timesheet.end_date)


def _time_entry_key(time_entry_id: str) -> str:
	return time_entry_id


def _iterate(client: OpenProjectClient, path: str, params=None, page_size: int = 100):
	offset = 1
	query = params or {}
	while True:
		payload = client.get(path, params={**query, "pageSize": page_size, "offset": offset})
		elements = (payload.get("_embedded") or {}).get("elements") or []
		if not elements:
			break

		yield from elements

		if len(elements) < page_size:
			break

		offset += 1


def _project_rows(project_id: str) -> list[Any]:
	return frappe.get_all(
		"Project",
		filters={"openproject_project_id": str(project_id)},
		fields=["name"],
	)


def _task_rows(work_package_id: str) -> list[Any]:
	return frappe.get_all(
		"Task",
		filters={"openproject_work_package_id": str(work_package_id)},
		fields=["name"],
	)


def validate_project_mapping_on_save(doc, method=None):
	project_id = _normalize_id(doc.get("openproject_project_id"))
	if not project_id:
		return

	matches = [row.name for row in _project_rows(project_id) if row.name != doc.name]
	if matches:
		frappe.throw(
			_("OpenProject project {0} is already mapped to: {1}").format(
				project_id,
				", ".join(matches),
			)
		)


def validate_task_mapping_on_save(doc, method=None):
	work_package_id = _normalize_id(doc.get("openproject_work_package_id"))
	if not work_package_id:
		return

	matches = [row.name for row in _task_rows(work_package_id) if row.name != doc.name]
	if matches:
		frappe.throw(
			_("OpenProject work package {0} is already mapped to: {1}").format(
				work_package_id,
				", ".join(matches),
			)
		)


def _project_identifier(project_payload: dict[str, Any], project_id: str) -> str:
	return project_payload.get("identifier") or project_payload.get("name") or f"openproject-{project_id}"


def _project_notes(project_payload: dict[str, Any], identifier: str) -> str:
	project_name = _normalize_id(project_payload.get("name"))
	description = _parse_formattable(project_payload.get("description")).strip()
	parts = []
	if project_name and project_name != identifier:
		parts.append(project_name)
	if description and description not in parts:
		parts.append(description)
	return "\n\n".join(parts)


def _project_name_by_identifier(identifier: str) -> str | None:
	return frappe.db.get_value(
		"Project",
		{"project_name": identifier},
		"name",
	)


def _customer_name_by_identifier(identifier: str | None) -> str | None:
	value = _normalize_id(identifier)
	if not value:
		return None
	return frappe.db.get_value("Customer", {"name": value}, "name") or frappe.db.get_value(
		"Customer", {"customer_name": value}, "name"
	)


def _project_customer(project_payload: dict[str, Any]) -> str | None:
	candidates: list[str] = []

	def add_candidate(value: Any) -> None:
		normalized = _normalize_id(value)
		if normalized and normalized not in candidates:
			candidates.append(normalized)

	add_candidate(project_payload.get("identifier"))
	add_candidate(project_payload.get("name"))

	parent_payload = (project_payload.get("_embedded") or {}).get("parent") or {}
	parent_link = ((project_payload.get("_links") or {}).get("parent") or {}).get("href")
	parent_is_project = bool(parent_payload) or str(parent_link or "").startswith("/api/v3/projects/")
	if parent_is_project:
		add_candidate(parent_payload.get("identifier"))
		add_candidate(parent_payload.get("name"))
		add_candidate(((project_payload.get("_links") or {}).get("parent") or {}).get("title"))

	for candidate in candidates:
		customer_name = _customer_name_by_identifier(candidate)
		if customer_name:
			return customer_name

	return None


def _new_project_doc(
	site_name: str, project_id: str, identifier: str, notes: str, customer_name: str | None = None
):
	return frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": identifier,
			"notes": notes,
			"openproject_url": f"{OpenProjectClient(site_name).base_url}/projects/{project_id}",
			"openproject_project_id": str(project_id),
			"customer": customer_name,
		}
	)


def _ensure_project(
	project_id: str, project_payload: dict[str, Any] | None = None, site_name: str | None = None
) -> str:
	site_name = _site_name(site_name)
	rows = _project_rows(project_id)
	if len(rows) > 1:
		frappe.throw(_("OpenProject project {0} is mapped to multiple ERPNext Projects").format(project_id))

	client = OpenProjectClient(site_name)
	payload = project_payload or client.get(f"/projects/{project_id}")
	identifier = _project_identifier(payload, project_id)
	notes = _project_notes(payload, identifier)
	customer_name = _project_customer(payload)
	existing_name = _project_name_by_identifier(identifier)

	if existing_name:
		project = frappe.get_doc("Project", existing_name)
	elif rows:
		project = frappe.get_doc("Project", rows[0].name)
	else:
		project = None

	if project:
		changed = False
		for fieldname, value in {
			"project_name": identifier,
			"notes": notes,
			"openproject_url": f"{client.base_url}/projects/{project_id}",
			"openproject_project_id": str(project_id),
			"customer": customer_name,
		}.items():
			if hasattr(project, fieldname) and (project.get(fieldname) or "") != value:
				project.set(fieldname, value)
				changed = True

		if changed:
			project.flags.ignore_permissions = True
			project.save(ignore_permissions=True)
		return project.name

	project_doc = _new_project_doc(site_name, project_id, identifier, notes, customer_name)
	project_doc.flags.ignore_permissions = True
	project_doc.insert(ignore_permissions=True)
	return project_doc.name


def _task_status(work_package: dict[str, Any]) -> str:
	status = (((work_package.get("_links") or {}).get("status") or {}).get("title") or "").strip()
	if status.lower() in {"closed", "done", "resolved"}:
		return "Completed"
	if status.lower() in {"in progress", "in specification", "working"}:
		return "Working"
	return "Open"


def _ensure_task(
	work_package_id: str, work_package: dict[str, Any] | None = None, site_name: str | None = None
) -> str | None:
	site_name = _site_name(site_name)
	rows = _task_rows(work_package_id)
	if len(rows) > 1:
		frappe.throw(
			_("OpenProject work package {0} is mapped to multiple ERPNext Tasks").format(work_package_id)
		)

	client = OpenProjectClient(site_name)
	payload = work_package or client.get(f"/work_packages/{work_package_id}")
	project_id = _extract_id(((payload.get("_links") or {}).get("project") or {}).get("href"))
	if not project_id:
		return None

	project_name = _ensure_project(project_id, site_name=site_name)
	subject = _normalize_id(payload.get("subject")) or f"OpenProject #{work_package_id}"
	description = _parse_formattable(payload.get("description")).strip()
	values = {
		"subject": subject,
		"project": project_name,
		"status": _task_status(payload),
		"description": description,
		"exp_start_date": payload.get("startDate"),
		"exp_end_date": payload.get("dueDate"),
		"openproject_work_package_id": str(work_package_id),
		"openproject_url": client.get_work_package_url(work_package_id),
	}

	task = frappe.get_doc("Task", rows[0].name) if rows else frappe.get_doc({"doctype": "Task"})
	changed = not rows
	for fieldname, value in values.items():
		if hasattr(task, fieldname) and (task.get(fieldname) or "") != (value or ""):
			task.set(fieldname, value)
			changed = True

	if not changed:
		return task.name

	task.flags.ignore_permissions = True
	if rows:
		task.save(ignore_permissions=True)
	else:
		task.insert(ignore_permissions=True)
	return task.name


def _resolve_employee_from_time_entry(client: OpenProjectClient, time_entry: dict[str, Any]) -> str | None:
	user = (time_entry.get("_embedded") or {}).get("user") or {}
	user_id = _normalize_id(user.get("id")) or _extract_id(
		((time_entry.get("_links") or {}).get("user") or {}).get("href")
	)
	if user_id and "mail" not in user and "email" not in user:
		try:
			user = client.get(f"/users/{user_id}") or user
		except Exception:
			pass

	lookup_values = [
		(user.get("mail") or "").strip().lower(),
		(user.get("email") or "").strip().lower(),
		(user.get("login") or "").strip().lower(),
	]
	lookup_values = [value for value in lookup_values if value]

	for lookup in lookup_values:
		employee = frappe.db.get_value("Employee", {"company_email": lookup}, "name") or frappe.db.get_value(
			"Employee", {"personal_email": lookup}, "name"
		)
		if employee:
			return employee

		user_name = frappe.db.get_value("User", {"email": lookup}, "name")
		if user_name:
			employee = frappe.db.get_value("Employee", {"user_id": user_name}, "name")
			if employee:
				return employee

	return None


def _ensure_activity_type(activity_name: str | None) -> str:
	activity = (activity_name or "").strip() or "Default"
	if not frappe.db.exists("Activity Type", activity):
		frappe.get_doc({"doctype": "Activity Type", "activity_type": activity}).insert(
			ignore_permissions=True
		)
	return activity


def _find_covering_timesheet(employee: str, spent_on: str, docstatus: int) -> str | None:
	return frappe.db.get_value(
		"Timesheet",
		{
			"employee": employee,
			"docstatus": docstatus,
			"start_date": ("<=", spent_on),
			"end_date": (">=", spent_on),
		},
		"name",
	)


def _find_daily_draft_timesheet(employee: str, spent_on: str) -> str | None:
	return _find_covering_timesheet(employee, spent_on, 0)


def _create_daily_draft_timesheet(employee: str, spent_on: str, row_values: dict[str, Any]) -> str | None:
	if _find_covering_timesheet(employee, spent_on, 1):
		return None

	timesheet = frappe.get_doc(
		{
			"doctype": "Timesheet",
			"employee": employee,
			"start_date": spent_on,
			"end_date": spent_on,
			"time_logs": [row_values],
		}
	)
	timesheet.flags.ignore_permissions = True
	timesheet.insert(ignore_permissions=True)
	return timesheet.name


def _timesheet_row_by_name(timesheet: Any, row_name: str) -> Any | None:
	for row in timesheet.get("time_logs") or []:
		if row.name == row_name:
			return row
	return None


def _row_changes(row: Any, values: dict[str, Any]) -> dict[str, Any]:
	changes: dict[str, Any] = {}
	for fieldname, new_value in values.items():
		current = getattr(row, fieldname, None)
		if fieldname == "hours":
			if abs(float(current or 0) - float(new_value or 0)) > 0.0001:
				changes[fieldname] = new_value
		elif (current or "") != (new_value or ""):
			changes[fieldname] = new_value
	return changes


def _delete_empty_draft_timesheet(timesheet: Any) -> None:
	if int(timesheet.docstatus or 0) == 0 and not (timesheet.get("time_logs") or []):
		frappe.delete_doc("Timesheet", timesheet.name, ignore_permissions=True)


def _time_entry_description(time_entry: dict[str, Any], work_package_id: str | None) -> str:
	comment = _parse_formattable(time_entry.get("comment")).strip()
	if comment:
		return comment
	title = (
		((time_entry.get("_embedded") or {}).get("workPackage") or {}).get("subject")
		or ((time_entry.get("_links") or {}).get("workPackage") or {}).get("title")
		or ((time_entry.get("_links") or {}).get("entity") or {}).get("title")
	)
	if work_package_id and title:
		return f"#{work_package_id} {title}"
	if work_package_id:
		return f"#{work_package_id}"
	return title or ""


def _time_entry_row_values(site_name: str, time_entry: dict[str, Any]) -> dict[str, Any]:
	project_payload = (time_entry.get("_embedded") or {}).get("project") or {}
	project_id = _normalize_id(project_payload.get("id")) or _extract_id(
		((time_entry.get("_links") or {}).get("project") or {}).get("href")
	)
	if not project_id:
		frappe.throw(_("Time entry {0} is missing its OpenProject project").format(time_entry.get("id")))

	project_name = _ensure_project(project_id, project_payload or None, site_name=site_name)
	work_package_id = (
		_normalize_id(((time_entry.get("_embedded") or {}).get("workPackage") or {}).get("id"))
		or _extract_id(((time_entry.get("_links") or {}).get("workPackage") or {}).get("href"))
		or _extract_id(((time_entry.get("_links") or {}).get("entity") or {}).get("href"))
	)
	work_package = (time_entry.get("_embedded") or {}).get("workPackage") or None
	task_name = _ensure_task(work_package_id, work_package, site_name=site_name) if work_package_id else None
	spent_on = str(time_entry.get("spentOn") or "")
	start_time = _parse_op_datetime(time_entry.get("startTime")) or (
		f"{spent_on} 00:00:00" if spent_on else None
	)
	activity_title = ((time_entry.get("_embedded") or {}).get("activity") or {}).get("name") or (
		(time_entry.get("_links") or {}).get("activity") or {}
	).get("title")
	row_values = {
		"project": project_name,
		"task": task_name,
		"hours": _parse_duration(time_entry.get("hours")),
		"description": _time_entry_description(time_entry, work_package_id),
		"activity_type": _ensure_activity_type(activity_title),
		"from_time": start_time,
		"to_time": _parse_op_datetime(time_entry.get("endTime")),
		"openproject_time_entry_id": _time_entry_key(str(time_entry.get("id"))),
		"openproject_work_package_url": get_openproject_work_package_url(site_name, work_package_id),
	}
	return row_values


def _upsert_time_entry(time_entry: dict[str, Any], site_name: str | None = None) -> str:
	site_name = _site_name(site_name)
	client = OpenProjectClient(site_name)
	time_entry_id = _normalize_id(time_entry.get("id"))
	if not time_entry_id:
		return "skipped"

	employee = _resolve_employee_from_time_entry(client, time_entry)
	if not employee:
		return "skipped"

	spent_on = str(time_entry.get("spentOn") or "")
	if not spent_on:
		return "skipped"

	row_values = _time_entry_row_values(site_name, time_entry)
	external_key = row_values["openproject_time_entry_id"]
	existing_detail_name = frappe.db.get_value(
		"Timesheet Detail",
		{"openproject_time_entry_id": external_key},
		"name",
	)

	if existing_detail_name:
		detail = frappe.get_doc("Timesheet Detail", existing_detail_name)
		parent = frappe.get_doc("Timesheet", detail.parent)
		if int(parent.docstatus or 0) == 1:
			return "locked"

		target_name = parent.name
		if not _timesheet_covers_date(parent, spent_on):
			target_name = _find_daily_draft_timesheet(employee, spent_on)
			if not target_name:
				target_name = _create_daily_draft_timesheet(employee, spent_on, row_values)
			if not target_name:
				return "locked"

		if target_name != parent.name:
			target = frappe.get_doc("Timesheet", target_name)
			row = _timesheet_row_by_name(parent, detail.name)
			if row:
				parent.time_logs = [child for child in parent.time_logs if child.name != detail.name]
				parent.flags.ignore_permissions = True
				parent.save(ignore_permissions=True)
				target.append("time_logs", row_values)
				target.flags.ignore_permissions = True
				target.save(ignore_permissions=True)
				_delete_empty_draft_timesheet(parent)
				return "updated"

		row = _timesheet_row_by_name(parent, detail.name)
		if not row:
			return "skipped"

		changes = _row_changes(row, row_values)
		if not changes:
			return "unchanged"

		for fieldname, value in changes.items():
			setattr(row, fieldname, value)
		parent.flags.ignore_permissions = True
		parent.save(ignore_permissions=True)
		return "updated"

	timesheet_name = _find_daily_draft_timesheet(employee, spent_on)
	if not timesheet_name:
		timesheet_name = _create_daily_draft_timesheet(employee, spent_on, row_values)
		if not timesheet_name:
			return "locked"
		return "created"

	timesheet = frappe.get_doc("Timesheet", timesheet_name)
	timesheet.append("time_logs", row_values)
	timesheet.flags.ignore_permissions = True
	timesheet.save(ignore_permissions=True)
	return "created"


@frappe.whitelist()
def sync_project_by_openproject_id(
	openproject_project_id: str, site_name: str | None = None
) -> dict[str, Any]:
	project_name = _ensure_project(str(openproject_project_id), site_name=site_name)
	return {"created_or_updated": True, "project": project_name}


@frappe.whitelist()
def sync_work_package_from_openproject(work_package_id: str, site_name: str | None = None) -> dict[str, Any]:
	site_name = _site_name(site_name)
	client = OpenProjectClient(site_name)
	work_package = client.get(f"/work_packages/{work_package_id}")
	project_id = _extract_id(((work_package.get("_links") or {}).get("project") or {}).get("href"))
	if not project_id:
		return {"skipped": True, "reason": "missing_project"}
	project_name = _ensure_project(project_id, site_name=site_name)
	task_name = _ensure_task(str(work_package_id), work_package, site_name=site_name)
	return {"created_or_updated": True, "project": project_name, "task": task_name}


@frappe.whitelist()
def sync_time_entry_from_openproject(time_entry_id: str, site_name: str | None = None) -> dict[str, Any]:
	site_name = _site_name(site_name)
	client = OpenProjectClient(site_name)
	time_entry = client.get(f"/time_entries/{time_entry_id}")
	action = _upsert_time_entry(time_entry, site_name=site_name)
	return {action: True}


def _delete_time_entry(time_entry_id: str) -> dict[str, Any]:
	external_key = _time_entry_key(str(time_entry_id))
	detail_name = frappe.db.get_value(
		"Timesheet Detail",
		{"openproject_time_entry_id": external_key},
		"name",
	)
	if not detail_name:
		return {"missing": True}

	detail = frappe.get_doc("Timesheet Detail", detail_name)
	timesheet = frappe.get_doc("Timesheet", detail.parent)
	if int(timesheet.docstatus or 0) == 1:
		return {"locked": True, "timesheet": timesheet.name}

	timesheet.time_logs = [row for row in timesheet.time_logs if row.name != detail_name]
	timesheet.flags.ignore_permissions = True
	timesheet.save(ignore_permissions=True)
	_delete_empty_draft_timesheet(timesheet)
	return {"deleted": True, "timesheet": timesheet.name}


def _delete_work_package(work_package_id: str) -> dict[str, Any]:
	rows = _task_rows(str(work_package_id))
	if not rows:
		return {"missing": True}
	if len(rows) > 1:
		frappe.throw(
			_("OpenProject work package {0} is mapped to multiple ERPNext Tasks").format(work_package_id)
		)

	task = frappe.get_doc("Task", rows[0].name)
	if task.get("status") != "Cancelled":
		task.status = "Cancelled"
		task.flags.ignore_permissions = True
		task.save(ignore_permissions=True)
	return {"deleted": True, "task": task.name}


def _time_entry_filters(synced_until: str | None) -> list[dict[str, Any]]:
	cursor = _parse_op_datetime_value(synced_until)
	if not cursor:
		return []
	since = cursor - SYNC_OVERLAP
	return [{"updated_at": {"operator": ">=", "values": [_format_op_datetime(since)]}}]


def _time_entry_reconcile_params(synced_until: str | None) -> dict[str, str]:
	params = {"sortBy": json.dumps([["updated_at", "asc"], ["id", "asc"]])}
	filters = _time_entry_filters(synced_until)
	if filters:
		params["filters"] = json.dumps(filters)
	return params


def _remember_time_entry_cursor(site_name: str, latest_updated_at: datetime | None) -> None:
	if not latest_updated_at:
		return
	frappe.db.set_value(
		"OpenProject Site",
		site_name,
		"time_entries_synced_until",
		latest_updated_at.astimezone(UTC).replace(tzinfo=None),
		update_modified=False,
	)


@frappe.whitelist()
def reconcile_openproject_time_entries(openproject_site: str | None = None) -> dict[str, Any]:
	site_name = _site_name(openproject_site)
	synced_until = frappe.db.get_value("OpenProject Site", site_name, "time_entries_synced_until")
	client = OpenProjectClient(site_name)
	result = {"created": 0, "updated": 0, "unchanged": 0, "locked": 0, "skipped": 0}
	latest_updated_at: datetime | None = None
	for time_entry in _iterate(
		client,
		"/time_entries",
		params=_time_entry_reconcile_params(synced_until),
	):
		updated_at = _parse_op_datetime_value(time_entry.get("updatedAt"))
		if updated_at and (not latest_updated_at or updated_at > latest_updated_at):
			latest_updated_at = updated_at

		action = _upsert_time_entry(time_entry, site_name=site_name)
		if action not in result:
			action = "skipped"
		result[action] += 1
	_remember_time_entry_cursor(site_name, latest_updated_at)
	return result


def _request_body() -> bytes:
	request = getattr(frappe.local, "request", None)
	if not request:
		return b""
	return request.get_data() or b""


def _request_json() -> dict[str, Any]:
	request = getattr(frappe.local, "request", None)
	payload = request.get_json(silent=True) if request else None
	if isinstance(payload, dict):
		return payload
	return dict(frappe.form_dict or {})


def _verify_webhook_signature(site_name: str, body: bytes) -> None:
	secret = frappe.get_doc("OpenProject Site", site_name).get_password(fieldname="webhook_secret") or ""
	if not secret:
		return

	signature = frappe.get_request_header("X-OP-Signature") or ""
	expected = "sha1=" + hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
	if not hmac.compare_digest(signature, expected):
		frappe.throw(_("Invalid OpenProject webhook signature"))


def _payload_id(payload: dict[str, Any], key: str) -> str | None:
	value = payload.get(key) or {}
	return _normalize_id(value.get("id"))


def _enqueue_webhook_action(site_name: str, payload: dict[str, Any]) -> dict[str, Any]:
	action = _normalize_id(payload.get("action"))
	if action not in OPENPROJECT_WEBHOOK_ACTIONS:
		return {"ignored": True, "action": action}

	if action.startswith("project:"):
		project_id = _payload_id(payload, "project")
		if project_id:
			enqueue_sync_project_by_openproject_id(site_name, project_id)
			return {"queued": True, "action": action, "project_id": project_id}

	if action in {"work_package:created", "work_package:updated"}:
		work_package_id = _payload_id(payload, "work_package")
		if work_package_id:
			enqueue_sync_work_package(site_name, work_package_id)
			return {"queued": True, "action": action, "work_package_id": work_package_id}

	if action == "work_package:deleted":
		work_package_id = _payload_id(payload, "work_package")
		if work_package_id:
			return {"action": action, **_delete_work_package(work_package_id)}

	if action in {"time_entry:created", "time_entry:updated"}:
		time_entry_id = _payload_id(payload, "time_entry")
		if time_entry_id:
			enqueue_sync_time_entry(site_name, time_entry_id)
			return {"queued": True, "action": action, "time_entry_id": time_entry_id}

	if action == "time_entry:deleted":
		time_entry_id = _payload_id(payload, "time_entry")
		if time_entry_id:
			return {"action": action, **_delete_time_entry(time_entry_id)}

	return {"skipped": True, "action": action, "reason": "missing_id"}


@frappe.whitelist(allow_guest=True)
def openproject_webhook(openproject_site: str | None = None) -> dict[str, Any]:
	site_name = _site_name(openproject_site)
	body = _request_body()
	_verify_webhook_signature(site_name, body)
	return _enqueue_webhook_action(site_name, _request_json())


def enqueue_sync_project_by_openproject_id(site_name: str, openproject_project_id: str) -> None:
	frappe.enqueue(
		"working_time.openproject_sync.sync_project_by_openproject_id",
		site_name=site_name,
		openproject_project_id=openproject_project_id,
		queue=SYNC_QUEUE,
		timeout=SYNC_TIMEOUT,
		enqueue_after_commit=True,
	)


def enqueue_sync_work_package(site_name: str, work_package_id: str) -> None:
	frappe.enqueue(
		"working_time.openproject_sync.sync_work_package_from_openproject",
		site_name=site_name,
		work_package_id=work_package_id,
		queue=SYNC_QUEUE,
		timeout=SYNC_TIMEOUT,
		enqueue_after_commit=True,
	)


def enqueue_sync_time_entry(site_name: str, time_entry_id: str) -> None:
	frappe.enqueue(
		"working_time.openproject_sync.sync_time_entry_from_openproject",
		site_name=site_name,
		time_entry_id=time_entry_id,
		queue=SYNC_QUEUE,
		timeout=SYNC_TIMEOUT,
		enqueue_after_commit=True,
	)
