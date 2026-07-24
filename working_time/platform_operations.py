from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import frappe
import requests
from frappe import _

from .openproject_client import OpenProjectClient

SYNC_QUEUE = "long"
SYNC_TIMEOUT = 600


def _now() -> datetime:
	return datetime.now(UTC).replace(tzinfo=None)


def _only_system_manager() -> None:
	frappe.only_for("System Manager")


def _json(value: Any) -> str:
	return json.dumps(value or {}, default=str, sort_keys=True)


def _settings():
	return frappe.get_single("Platform Operations Settings")


def _append_step(doc: Any, step: str, status: str, detail: str = "") -> None:
	doc.append(
		"steps",
		{
			"step": step,
			"status": status,
			"detail": detail,
			"completed_at": _now(),
		},
	)


def _project_context(project_name: str | None) -> tuple[str | None, str | None]:
	if not project_name:
		return None, None
	return project_name, frappe.db.get_value("Project", project_name, "customer")


def _event_context(object_type: str | None, object_id: str | None) -> tuple[str | None, str | None]:
	if object_type == "work_package" and object_id:
		project = frappe.db.get_value("Task", {"openproject_work_package_id": object_id}, "project")
		return _project_context(project)
	if object_type == "time_entry" and object_id:
		detail_name = frappe.db.get_value(
			"Timesheet Detail",
			{"openproject_time_entry_id": object_id},
			"name",
		)
		if detail_name:
			project = frappe.db.get_value("Timesheet Detail", detail_name, "project")
			return _project_context(project)
	if object_type == "project" and object_id:
		project = frappe.db.get_value("Project", {"openproject_project_id": object_id}, "name")
		return _project_context(project)
	return None, None


def create_openproject_webhook_event(
	site_name: str,
	payload: dict[str, Any],
	status: str,
	result: dict[str, Any] | None = None,
	error: str | None = None,
) -> str:
	from .openproject_sync import _webhook_object

	action = str(payload.get("action") or "")
	object_type, object_id = _webhook_object(payload)
	project, customer = _event_context(object_type, object_id)
	doc = frappe.get_doc(
		{
			"doctype": "OpenProject Webhook Event",
			"openproject_site": site_name,
			"action": action,
			"object_type": object_type,
			"object_id": object_id,
			"customer": customer,
			"project": project,
			"status": status,
			"payload_json": _json(payload),
			"result_json": _json(result),
			"error": error,
			"attempt_count": 0,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def queue_openproject_webhook_event(event_name: str) -> None:
	frappe.enqueue(
		"working_time.platform_operations.process_openproject_webhook_event",
		event_name=event_name,
		queue=SYNC_QUEUE,
		timeout=SYNC_TIMEOUT,
		enqueue_after_commit=True,
	)


def _dispatch_openproject_event(event: Any) -> dict[str, Any]:
	from . import openproject_sync

	payload = json.loads(event.payload_json or "{}")
	action = event.action
	object_id = event.object_id
	if action.startswith("project:") and object_id:
		return openproject_sync.sync_project_by_openproject_id(event.openproject_site, object_id)
	if action in {"work_package:created", "work_package:updated"} and object_id:
		return openproject_sync.sync_work_package_from_openproject(object_id, event.openproject_site)
	if action == "work_package:deleted" and object_id:
		return openproject_sync.delete_work_package_from_openproject(object_id)
	if action in {"time_entry:created", "time_entry:updated"} and object_id:
		return openproject_sync.sync_time_entry_from_openproject(object_id, event.openproject_site)
	if action == "time_entry:deleted" and object_id:
		return openproject_sync.delete_time_entry_from_openproject(object_id)
	return {"ignored": True, "reason": "unsupported_or_missing_object", "payload": payload}


def _set_event_status(event: Any, status: str, result: dict[str, Any] | None = None, error: str = "") -> None:
	event.status = status
	event.result_json = _json(result)
	event.error = error
	if status == "Processing":
		event.started_at = event.started_at or _now()
		event.last_attempt_at = _now()
		event.attempt_count = int(event.attempt_count or 0) + 1
	if status in {"Processed", "Failed", "Locked", "Ignored"}:
		event.completed_at = _now()
	event.flags.ignore_permissions = True
	event.save(ignore_permissions=True)


def process_openproject_webhook_event(event_name: str) -> dict[str, Any]:
	event = frappe.get_doc("OpenProject Webhook Event", event_name)
	if event.status in {"Processed", "Ignored"}:
		return {"ignored": True, "reason": "already_final"}
	_set_event_status(event, "Processing")
	try:
		result = _dispatch_openproject_event(event)
		status = "Locked" if result.get("locked") else "Ignored" if result.get("ignored") else "Processed"
		_set_event_status(event, status, result)
		if status == "Locked":
			send_platform_alert(
				"openproject-sync-locked",
				"Warning",
				f"OpenProject synchronization is locked for {event.action} {event.object_id}.",
				dedupe_key=f"openproject-locked:{event.action}:{event.object_id}",
				customer=event.customer,
				project=event.project,
			)
		return result
	except frappe.RetryBackgroundJobError as exc:
		if int(event.attempt_count or 0) >= 5:
			_set_event_status(event, "Failed", error=f"Retry limit reached: {exc}")
			send_platform_alert(
				"openproject-sync-failed",
				"Error",
				f"OpenProject synchronization exhausted retries for {event.action} {event.object_id}: {exc}",
				dedupe_key=f"openproject-failed:{event.action}:{event.object_id}",
				customer=event.customer,
				project=event.project,
			)
			return {"failed": True, "reason": "retry_limit_reached"}
		_set_event_status(event, "Queued", error=str(exc))
		raise
	except Exception as exc:
		_set_event_status(event, "Failed", error=str(exc))
		send_platform_alert(
			"openproject-sync-failed",
			"Error",
			f"OpenProject synchronization failed for {event.action} {event.object_id}: {exc}",
			dedupe_key=f"openproject-failed:{event.action}:{event.object_id}",
			customer=event.customer,
			project=event.project,
		)
		raise


@frappe.whitelist()
def retry_openproject_webhook_event(event_name: str) -> dict[str, str]:
	_only_system_manager()
	event = frappe.get_doc("OpenProject Webhook Event", event_name)
	if event.status != "Failed":
		frappe.throw(_("Only failed webhook events can be retried."))
	_set_event_status(event, "Queued", error="")
	queue_openproject_webhook_event(event.name)
	return {"name": event.name, "status": "Queued"}


def queue_reconciliation(reconciliation_type: str, openproject_site: str | None = None) -> str:
	from .openproject_sync import _site_name

	site_name = _site_name(openproject_site)
	doc = frappe.get_doc(
		{
			"doctype": "OpenProject Reconciliation Run",
			"openproject_site": site_name,
			"reconciliation_type": reconciliation_type,
			"status": "Queued",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	frappe.enqueue(
		"working_time.platform_operations.process_reconciliation_run",
		run_name=doc.name,
		queue=SYNC_QUEUE,
		timeout=SYNC_TIMEOUT,
		enqueue_after_commit=True,
	)
	return doc.name


def queue_incremental_time_entry_reconciliation() -> str:
	return queue_reconciliation("Time Entries")


def queue_project_and_work_package_reconciliation() -> str:
	return queue_reconciliation("Projects and Work Packages")


def queue_time_entry_deletion_reconciliation() -> str:
	return queue_reconciliation("Time Entry Deletions")


def _reconciliation_function(reconciliation_type: str):
	from . import openproject_sync

	functions = {
		"Time Entries": openproject_sync.reconcile_openproject_time_entries,
		"Projects and Work Packages": openproject_sync.reconcile_openproject_projects_and_work_packages,
		"Time Entry Deletions": openproject_sync.reconcile_openproject_time_entry_deletions,
	}
	if reconciliation_type not in functions:
		frappe.throw(_("Unknown reconciliation type: {0}").format(reconciliation_type))
	return functions[reconciliation_type]


def process_reconciliation_run(run_name: str) -> dict[str, Any]:
	run = frappe.get_doc("OpenProject Reconciliation Run", run_name)
	run.status = "Processing"
	run.started_at = _now()
	run.flags.ignore_permissions = True
	run.save(ignore_permissions=True)
	try:
		result = _reconciliation_function(run.reconciliation_type)(run.openproject_site)
		run.status = "Processed"
		run.result_json = _json(result)
		run.completed_at = _now()
		frappe.db.set_value(
			"OpenProject Site",
			run.openproject_site,
			{"last_reconciliation_at": run.completed_at, "last_reconciliation_status": "Processed"},
			update_modified=False,
		)
		exceptional = int(result.get("locked", 0) or 0) + int(result.get("deleted", 0) or 0)
		if exceptional:
			send_platform_alert(
				"openproject-reconciliation-exception",
				"Warning",
				f"{run.reconciliation_type} completed with {exceptional} exceptional records.",
				dedupe_key=f"openproject-reconciliation:{run.openproject_site}:{run.reconciliation_type}",
			)
		return result
	except Exception as exc:
		run.status = "Failed"
		run.error = str(exc)
		run.completed_at = _now()
		frappe.db.set_value(
			"OpenProject Site",
			run.openproject_site,
			{"last_reconciliation_at": run.completed_at, "last_reconciliation_status": "Failed"},
			update_modified=False,
		)
		send_platform_alert(
			"openproject-reconciliation-failed",
			"Error",
			f"{run.reconciliation_type} failed for {run.openproject_site}: {exc}",
			dedupe_key=f"openproject-reconciliation-failed:{run.openproject_site}:{run.reconciliation_type}",
		)
		raise
	finally:
		run.flags.ignore_permissions = True
		run.save(ignore_permissions=True)


def send_platform_alert(
	source: str,
	severity: str,
	message: str,
	*,
	dedupe_key: str,
	customer: str | None = None,
	project: str | None = None,
) -> str:
	settings = _settings()
	cooldown = max(int(settings.alert_cooldown_minutes or 60), 1)
	previous = frappe.get_all(
		"Platform Alert",
		filters={"dedupe_key": dedupe_key},
		fields=["name", "last_sent_at", "occurrence_count"],
		order_by="creation desc",
		limit_page_length=1,
	)
	suppressed = False
	if previous and previous[0].last_sent_at:
		delta = _now() - previous[0].last_sent_at
		suppressed = delta.total_seconds() < cooldown * 60
	alert = frappe.get_doc(
		{
			"doctype": "Platform Alert",
			"dedupe_key": dedupe_key,
			"source": source,
			"severity": severity,
			"status": "Suppressed" if suppressed else "Recorded",
			"customer": customer,
			"project": project,
			"occurrence_count": int(previous[0].occurrence_count or 0) + 1 if previous else 1,
			"message": message,
		}
	)
	if suppressed:
		alert.flags.ignore_permissions = True
		alert.insert(ignore_permissions=True)
		return alert.name
	webhook_url = (settings.teams_webhook_url or "").strip()
	if not webhook_url:
		alert.status = "Recorded"
		alert.flags.ignore_permissions = True
		alert.insert(ignore_permissions=True)
		return alert.name
	try:
		response = requests.post(
			webhook_url,
			json={"text": f"**{severity}** · {source}\n{message}"},
			timeout=20,
		)
		response.raise_for_status()
		alert.status = "Sent"
		alert.last_sent_at = _now()
	except requests.RequestException as exc:
		alert.status = "Failed"
		alert.error = str(exc)
	alert.flags.ignore_permissions = True
	alert.insert(ignore_permissions=True)
	return alert.name


@frappe.whitelist()
def send_test_teams_alert() -> dict[str, str]:
	_only_system_manager()
	settings = _settings()
	if not (settings.teams_webhook_url or "").strip():
		frappe.throw(_("Enter and save a Teams webhook URL first."))
	name = send_platform_alert(
		"teams-configuration-test",
		"Info",
		"ERPNext successfully sent this test alert.",
		dedupe_key=f"teams-configuration-test:{_now().isoformat()}",
	)
	alert = frappe.get_doc("Platform Alert", name)
	if alert.status != "Sent":
		frappe.throw(
			_("Teams test alert failed: {0}").format(alert.error or _("No successful response was received."))
		)
	return {"name": name, "status": alert.status}


def _sales_order_project_name(sales_order: Any) -> str:
	return f"{sales_order.customer_name or sales_order.customer} — {sales_order.name}"


def _openproject_site_name() -> str:
	sites = frappe.get_all("OpenProject Site", pluck="name")
	if len(sites) != 1:
		frappe.throw(_("Exactly one OpenProject Site must be configured for customer provisioning."))
	return sites[0]


def _provisioning_preview(sales_order: Any) -> dict[str, Any]:
	return {
		"sales_order": sales_order.name,
		"customer": sales_order.customer,
		"erpnext_project": _sales_order_project_name(sales_order),
		"openproject_project_identifier": f"so-{sales_order.name}".lower(),
	}


@frappe.whitelist()
def prepare_customer_project_provisioning(sales_order_name: str) -> dict[str, Any]:
	_only_system_manager()
	sales_order = frappe.get_doc("Sales Order", sales_order_name)
	if int(sales_order.docstatus or 0) != 1:
		frappe.throw(_("Project provisioning is only available for submitted Sales Orders."))
	existing = frappe.db.get_value("Customer Project Provisioning", {"sales_order": sales_order.name}, "name")
	if existing:
		doc = frappe.get_doc("Customer Project Provisioning", existing)
		return {"name": doc.name, "preview": json.loads(doc.preview_json or "{}"), "status": doc.status}
	doc = frappe.get_doc(
		{
			"doctype": "Customer Project Provisioning",
			"sales_order": sales_order.name,
			"customer": sales_order.customer,
			"status": "Preview",
			"openproject_site": _openproject_site_name(),
			"preview_json": _json(_provisioning_preview(sales_order)),
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.set_value(
		"Sales Order",
		sales_order.name,
		"customer_project_provisioning",
		doc.name,
		update_modified=False,
	)
	return {"name": doc.name, "preview": json.loads(doc.preview_json), "status": doc.status}


@frappe.whitelist()
def confirm_customer_project_provisioning(provisioning_name: str) -> dict[str, str]:
	_only_system_manager()
	doc = frappe.get_doc("Customer Project Provisioning", provisioning_name)
	if doc.status not in {"Preview", "Failed"}:
		frappe.throw(_("Only a preview or failed provisioning can be confirmed."))
	doc.status = "Queued"
	doc.error = ""
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	frappe.enqueue(
		"working_time.platform_operations.process_customer_project_provisioning",
		provisioning_name=doc.name,
		queue=SYNC_QUEUE,
		timeout=SYNC_TIMEOUT,
		enqueue_after_commit=True,
	)
	return {"name": doc.name, "status": doc.status}


def _ensure_erpnext_project(provisioning: Any, sales_order: Any) -> str:
	existing = frappe.db.get_value("Project", {"source_sales_order": sales_order.name}, "name")
	if existing:
		return existing
	project = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": _sales_order_project_name(sales_order),
			"customer": sales_order.customer,
			"source_sales_order": sales_order.name,
		}
	)
	project.insert(ignore_permissions=True)
	return project.name


def _ensure_openproject_project(provisioning: Any, sales_order: Any) -> dict[str, Any]:
	if provisioning.openproject_project_id:
		return {
			"id": provisioning.openproject_project_id,
			"url": provisioning.openproject_url,
		}
	client = OpenProjectClient(provisioning.openproject_site)
	identifier = f"so-{sales_order.name}".lower()
	payload = client.post(
		"/projects",
		{"name": _sales_order_project_name(sales_order), "identifier": identifier},
	)
	project_id = str(payload["id"])
	return {"id": project_id, "url": f"{client.base_url}/projects/{project_id}"}


def process_customer_project_provisioning(provisioning_name: str) -> dict[str, str]:
	doc = frappe.get_doc("Customer Project Provisioning", provisioning_name)
	doc.status = "Processing"
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	try:
		sales_order = frappe.get_doc("Sales Order", doc.sales_order)
		project_name = _ensure_erpnext_project(doc, sales_order)
		doc.erpnext_project = project_name
		_append_step(doc, "ERPNext Project", "Completed", project_name)
		doc.save(ignore_permissions=True)

		op_project = _ensure_openproject_project(doc, sales_order)
		doc.openproject_project_id = op_project["id"]
		doc.openproject_url = op_project["url"]
		frappe.db.set_value(
			"Project",
			project_name,
			{"openproject_project_id": op_project["id"], "openproject_url": op_project["url"]},
			update_modified=False,
		)
		_append_step(doc, "OpenProject Project", "Completed", op_project["id"])
		doc.save(ignore_permissions=True)

		doc.status = "Completed"
		doc.completed_at = _now()
		doc.error = ""
		doc.save(ignore_permissions=True)
		return {"name": doc.name, "status": doc.status}
	except Exception as exc:
		doc.status = "Failed"
		doc.error = str(exc)
		_append_step(doc, "Provisioning", "Failed", str(exc))
		doc.save(ignore_permissions=True)
		send_platform_alert(
			"customer-provisioning-failed",
			"Error",
			f"Provisioning for Sales Order {doc.sales_order} failed: {exc}",
			dedupe_key=f"customer-provisioning:{doc.sales_order}",
			customer=doc.customer,
		)
		raise


def _billing_status(detail: Any, timesheet: Any) -> tuple[str, dict[str, Any]]:
	project_name = detail.get("project")
	if not project_name:
		return "Missing Project", {}
	project = frappe.get_doc("Project", project_name)
	if not project.customer:
		return "Missing Customer", {}
	sales_order = project.get("source_sales_order")
	if not sales_order or not frappe.db.exists("Sales Order", {"name": sales_order, "docstatus": 1}):
		return "Missing Sales Order", {"project": project}
	if frappe.db.exists(
		"Billing Review Item",
		{"timesheet_detail": detail.name, "status": ["in", ["Invoiced", "Already Invoiced"]]},
	):
		return "Already Invoiced", {"project": project, "sales_order": sales_order}
	if frappe.db.exists(
		"OpenProject Webhook Event",
		{"status": "Locked", "project": project.name},
	):
		return "Locked", {"project": project, "sales_order": sales_order}
	return "Eligible", {"project": project, "sales_order": sales_order}


@frappe.whitelist()
def create_billing_review(period_start: str, period_end: str) -> dict[str, Any]:
	_only_system_manager()
	if period_start > period_end:
		frappe.throw(_("Period start must be before period end."))
	review = frappe.get_doc(
		{
			"doctype": "Billing Review",
			"period_start": period_start,
			"period_end": period_end,
			"status": "Preview",
		}
	)
	timesheets = frappe.get_all(
		"Timesheet",
		filters={"docstatus": 1, "start_date": ("<=", period_end), "end_date": (">=", period_start)},
		fields=["name"],
	)
	counts: dict[str, int] = {}
	for row in timesheets:
		timesheet = frappe.get_doc("Timesheet", row.name)
		for detail in timesheet.get("time_logs") or []:
			status, context = _billing_status(detail, timesheet)
			project = context.get("project")
			hours = float(detail.get("billing_hours") or detail.get("hours") or 0)
			rate = float((project.get("billing_rate") if project else 0) or 0)
			review.append(
				"items",
				{
					"timesheet": timesheet.name,
					"timesheet_detail": detail.name,
					"customer": project.customer if project else None,
					"project": project.name if project else None,
					"sales_order": context.get("sales_order"),
					"hours": hours,
					"rate": rate,
					"amount": hours * rate,
					"status": status,
				},
			)
			counts[status] = counts.get(status, 0) + 1
	review.result_json = _json(counts)
	review.insert(ignore_permissions=True)
	return {"name": review.name, "counts": counts}


@frappe.whitelist()
def create_billing_invoice_drafts(review_name: str) -> dict[str, Any]:
	_only_system_manager()
	settings = _settings()
	if not settings.default_time_billing_item:
		frappe.throw(_("Set Default time billing item in Platform Operations Settings first."))
	review = frappe.get_doc("Billing Review", review_name)
	if review.status != "Preview":
		frappe.throw(_("Only a billing preview can create invoice drafts."))
	groups: dict[tuple[str, str], list[Any]] = {}
	for item in review.items:
		if item.status == "Eligible":
			groups.setdefault((item.customer, item.sales_order), []).append(item)
	invoices: list[str] = []
	for (customer, sales_order_name), items in groups.items():
		sales_order = frappe.get_doc("Sales Order", sales_order_name)
		invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": customer,
				"company": sales_order.company,
				"currency": sales_order.currency,
				"items": [
					{
						"item_code": settings.default_time_billing_item,
						"qty": item.hours,
						"rate": item.rate,
						"project": item.project,
						"sales_order": sales_order_name,
						"description": f"Time from {item.timesheet}",
					}
					for item in items
				],
			}
		)
		invoice.insert(ignore_permissions=True)
		invoices.append(invoice.name)
		for item in items:
			item.status = "Invoiced"
			item.sales_invoice = invoice.name
	review.created_invoice_count = len(invoices)
	review.status = "Invoiced"
	review.result_json = _json({"sales_invoices": invoices})
	review.save(ignore_permissions=True)
	return {"name": review.name, "sales_invoices": invoices}


@frappe.whitelist()
def get_integration_control_center(
	openproject_site: str | None = None,
	customer: str | None = None,
	project: str | None = None,
) -> dict[str, Any]:
	_only_system_manager()
	filters: dict[str, Any] = {}
	if openproject_site:
		filters["openproject_site"] = openproject_site
	if customer:
		filters["customer"] = customer
	if project:
		filters["project"] = project
	events = frappe.get_all(
		"OpenProject Webhook Event",
		filters={**filters, "status": ["in", ["Queued", "Processing", "Failed", "Locked"]]},
		fields=[
			"name",
			"action",
			"object_type",
			"object_id",
			"status",
			"attempt_count",
			"customer",
			"project",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=100,
	)
	runs = frappe.get_all(
		"OpenProject Reconciliation Run",
		filters={"openproject_site": openproject_site} if openproject_site else {},
		fields=["name", "openproject_site", "reconciliation_type", "status", "completed_at", "error"],
		order_by="creation desc",
		limit_page_length=30,
	)
	return {
		"events": events,
		"runs": runs,
		"counts": {
			"queued": sum(event.status == "Queued" for event in events),
			"failed": sum(event.status == "Failed" for event in events),
			"locked": sum(event.status == "Locked" for event in events),
		},
	}
