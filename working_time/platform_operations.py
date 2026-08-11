from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from math import isfinite
from typing import Any

import frappe
import requests
from frappe import _

SYNC_QUEUE = "long"
SYNC_TIMEOUT = 600
QUARTER_HOUR = Decimal("0.25")
CLAIMED_BILLING_STATUSES = ("Draft Created", "Invoiced", "Already Invoiced")
BILLING_MODELS = ("Non-billable", "Time and Material", "Fixed Price", "Recurring")


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


def _teams_adaptive_card(
	source: str,
	severity: str,
	message: str,
	customer: str | None = None,
	project: str | None = None,
) -> dict[str, Any]:
	color = {
		"Critical": "Attention",
		"Error": "Attention",
		"Warning": "Warning",
		"Info": "Accent",
	}.get(severity, "Default")
	facts = [{"title": _("Source"), "value": source}]
	if customer:
		facts.append({"title": _("Customer"), "value": customer})
	if project:
		facts.append({"title": _("Project"), "value": project})
	return {
		"type": "message",
		"attachments": [
			{
				"contentType": "application/vnd.microsoft.card.adaptive",
				"contentUrl": None,
				"content": {
					"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
					"type": "AdaptiveCard",
					"version": "1.2",
					"body": [
						{
							"type": "TextBlock",
							"text": f"{severity}: {source}",
							"weight": "Bolder",
							"size": "Medium",
							"color": color,
							"wrap": True,
						},
						{"type": "TextBlock", "text": message, "wrap": True},
						{"type": "FactSet", "facts": facts},
					],
				},
			}
		],
	}


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
			json=_teams_adaptive_card(source, severity, message, customer, project),
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
		"ERPNext sent this Adaptive Card to the configured Teams workflow.",
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


def _matching_sales_order_items(sales_order: Any, item_code: str | None) -> list[Any]:
	if not item_code:
		return []
	return [
		row
		for row in (_document_value(sales_order, "items", []) or [])
		if _document_value(row, "item_code") == item_code
	]


def _provisioning_preview(sales_order: Any, time_billing_item: str | None = None) -> dict[str, Any]:
	time_item_rows = _matching_sales_order_items(sales_order, time_billing_item)
	time_item_row = time_item_rows[0] if len(time_item_rows) == 1 else None
	return {
		"sales_order": sales_order.name,
		"customer": sales_order.customer,
		"erpnext_project": _sales_order_project_name(sales_order),
		"billing_models": list(BILLING_MODELS),
		"time_billing_item": time_billing_item,
		"time_billing_item_match_count": len(time_item_rows),
		"time_billing_item_row": _document_value(time_item_row, "name"),
		"suggested_billing_rate": float(_document_value(time_item_row, "rate") or 0),
	}


@frappe.whitelist()
def prepare_customer_project_provisioning(sales_order_name: str) -> dict[str, Any]:
	_only_system_manager()
	sales_order = frappe.get_doc("Sales Order", sales_order_name)
	if int(sales_order.docstatus or 0) != 1:
		frappe.throw(_("Project provisioning is only available for submitted Sales Orders."))
	settings = _settings()
	preview = _provisioning_preview(sales_order, settings.default_time_billing_item)
	existing = frappe.db.get_value("Customer Project Provisioning", {"sales_order": sales_order.name}, "name")
	if existing:
		doc = frappe.get_doc("Customer Project Provisioning", existing)
		if doc.status == "Preview":
			doc.preview_json = _json(preview)
			doc.save(ignore_permissions=True)
		return {"name": doc.name, "preview": json.loads(doc.preview_json or "{}"), "status": doc.status}
	doc = frappe.get_doc(
		{
			"doctype": "Customer Project Provisioning",
			"sales_order": sales_order.name,
			"customer": sales_order.customer,
			"status": "Preview",
			"preview_json": _json(preview),
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
def confirm_customer_project_provisioning(
	provisioning_name: str,
	billing_model: str | None = None,
	billing_rate: float | str | None = None,
) -> dict[str, str]:
	_only_system_manager()
	doc = frappe.get_doc("Customer Project Provisioning", provisioning_name)
	if doc.status not in {"Preview", "Failed"}:
		frappe.throw(_("Only a preview or failed provisioning can be confirmed."))
	selected_model = str(billing_model or doc.get("billing_model") or "").strip()
	if selected_model not in BILLING_MODELS:
		frappe.throw(_("Select a valid billing model before provisioning the project."))
	rate_value = billing_rate if billing_rate is not None else doc.get("billing_rate")
	try:
		selected_rate = float(rate_value or 0)
	except (TypeError, ValueError):
		frappe.throw(_("Billing rate must be a number."))
	if selected_model == "Time and Material":
		settings = _settings()
		if not settings.default_time_billing_item:
			frappe.throw(_("Set Default time billing item in Platform Operations Settings first."))
		sales_order = frappe.get_doc("Sales Order", doc.sales_order)
		time_item_row = _sales_order_time_billing_row(sales_order, settings.default_time_billing_item)
		if not isfinite(selected_rate) or selected_rate <= 0:
			frappe.throw(_("Time and Material projects require a positive billing rate."))
		sales_order_rate = float(_document_value(time_item_row, "rate") or 0)
		if _decimal(selected_rate) != _decimal(sales_order_rate):
			frappe.throw(
				_("The project billing rate must equal the Sales Order time item rate ({0}).").format(
					sales_order_rate
				)
			)
	else:
		selected_rate = 0
	doc.billing_model = selected_model
	doc.billing_rate = selected_rate
	preview = json.loads(doc.preview_json or "{}")
	preview.update({"billing_model": selected_model, "billing_rate": selected_rate})
	doc.preview_json = _json(preview)
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
	existing = frappe.db.get_value(
		"Project",
		{"sales_order": sales_order.name},
		["name", "customer", "billing_model", "billing_rate"],
		as_dict=True,
	)
	if existing:
		conflicts = []
		if existing.customer != sales_order.customer:
			conflicts.append("customer")
		if existing.billing_model != provisioning.billing_model:
			conflicts.append("billing model")
		if _decimal(existing.billing_rate) != _decimal(provisioning.billing_rate):
			conflicts.append("billing rate")
		if conflicts:
			frappe.throw(
				_("Existing Project {0} conflicts with provisioning for: {1}.").format(
					existing.name, ", ".join(conflicts)
				)
			)
		return str(existing.name)
	project = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": _sales_order_project_name(sales_order),
			"customer": sales_order.customer,
			"sales_order": sales_order.name,
			"billing_model": provisioning.billing_model,
			"billing_rate": float(provisioning.billing_rate or 0),
		}
	)
	project.insert(ignore_permissions=True)
	return project.name


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


def _document_value(document: Any, fieldname: str, default: Any = None) -> Any:
	if hasattr(document, "get"):
		return document.get(fieldname, default)
	return getattr(document, fieldname, default)


def _decimal(value: Any) -> Decimal:
	return Decimal(str(value or 0))


def _round_billable_hours(hours: Any) -> float:
	"""Round a non-negative aggregate upward to the next quarter hour."""
	value = max(_decimal(hours), Decimal(0))
	if not value:
		return 0.0
	return float((value / QUARTER_HOUR).to_integral_value(rounding=ROUND_CEILING) * QUARTER_HOUR)


def _billing_date(detail: Any, timesheet: Any) -> str:
	value = _document_value(detail, "from_time") or _document_value(timesheet, "start_date")
	if isinstance(value, datetime):
		return value.date().isoformat()
	if hasattr(value, "isoformat"):
		return value.isoformat()
	return str(value or "")[:10]


def _billing_source_references(item: Any) -> set[str]:
	references: set[str] = set()
	raw = _document_value(item, "source_details_json") or ""
	if raw:
		try:
			for source in json.loads(raw):
				if source.get("timesheet_detail"):
					references.add(str(source["timesheet_detail"]))
		except (TypeError, ValueError):
			pass
	legacy_reference = _document_value(item, "timesheet_detail")
	if legacy_reference:
		references.add(str(legacy_reference))
	return references


def _claimed_billing_sources(exclude_review: str | None = None) -> dict[str, str]:
	filters: dict[str, Any] = {"status": ["in", list(CLAIMED_BILLING_STATUSES)]}
	if exclude_review:
		filters["parent"] = ["!=", exclude_review]
	items = frappe.get_all(
		"Billing Review Item",
		filters=filters,
		fields=["timesheet_detail", "source_details_json", "status"],
	)
	claimed: dict[str, str] = {}
	for item in items:
		for source in _billing_source_references(item):
			claimed[source] = item.status
	return claimed


def _billing_status(detail: Any, claimed_sources: dict[str, str]) -> tuple[str, dict[str, Any]]:
	claimed_status = claimed_sources.get(str(detail.name))
	if claimed_status == "Draft Created":
		return "Already Drafted", {}
	if claimed_status:
		return "Already Invoiced", {}
	project_name = detail.get("project")
	if not project_name:
		return "Missing Project", {}
	project = frappe.get_doc("Project", project_name)
	if not project.customer:
		return "Missing Customer", {"project": project}
	if project.get("billing_model") != "Time and Material":
		return "Locked", {"project": project}
	if float(project.get("billing_rate") or 0) <= 0:
		return "Locked", {"project": project}
	sales_order = project.get("sales_order")
	if not sales_order or not frappe.db.exists("Sales Order", {"name": sales_order, "docstatus": 1}):
		return "Missing Sales Order", {"project": project}
	return "Eligible", {"project": project, "sales_order": sales_order}


def _aggregate_billing_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""Aggregate raw source entries before applying commercial rounding."""
	groups: dict[tuple[str, str, str | None, str], dict[str, Any]] = {}
	for source in sources:
		key = (source["customer"], source["project"], source.get("task"), source["work_date"])
		if key not in groups:
			groups[key] = {
				**source,
				"_actual_hours": Decimal(0),
				"_raw_billable_hours": Decimal(0),
				"sources": [],
			}
		group = groups[key]
		group["_actual_hours"] += _decimal(source.get("actual_hours"))
		group["_raw_billable_hours"] += _decimal(source.get("raw_billable_hours"))
		group["sources"].append(
			{
				"timesheet": source["timesheet"],
				"timesheet_detail": source["timesheet_detail"],
				"issue": source.get("issue"),
				"customer_description": source.get("customer_description"),
			}
		)

	result: list[dict[str, Any]] = []
	for group in groups.values():
		raw_billable_hours = group.pop("_raw_billable_hours")
		actual_hours = group.pop("_actual_hours")
		group["sources"].sort(key=lambda source: source["timesheet_detail"])
		group["actual_hours"] = float(actual_hours)
		group["raw_billable_hours"] = float(raw_billable_hours)
		group["hours"] = _round_billable_hours(raw_billable_hours)
		group["amount"] = group["hours"] * float(group["rate"] or 0)
		issues = sorted({source["issue"] for source in group["sources"] if source.get("issue")})
		descriptions = []
		for source in group["sources"]:
			description = source.get("customer_description")
			if description and description not in descriptions:
				descriptions.append(description)
		group["issue"] = issues[0] if len(issues) == 1 else None
		group["ticket_references"] = ", ".join(issues)
		group["customer_description"] = "; ".join(descriptions)
		result.append(group)
	return result


def _billing_source(detail: Any, timesheet: Any, status: str, context: dict[str, Any]) -> dict[str, Any]:
	project = context.get("project")
	billing_hours = detail.get("billing_hours")
	if billing_hours is None:
		billing_hours = detail.get("hours") if detail.get("is_billable") else 0
	return {
		"timesheet": timesheet.name,
		"timesheet_detail": detail.name,
		"customer": project.customer if project else None,
		"project": project.name if project else detail.get("project"),
		"task": detail.get("task"),
		"issue": detail.get("issue"),
		"customer_description": detail.get("customer_description") or detail.get("description"),
		"sales_order": context.get("sales_order"),
		"work_date": _billing_date(detail, timesheet),
		"actual_hours": float(detail.get("hours") or 0),
		"raw_billable_hours": float(billing_hours or 0),
		"rate": float((project.get("billing_rate") if project else 0) or 0),
		"status": status,
	}


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
	claimed_sources = _claimed_billing_sources()
	eligible_sources: list[dict[str, Any]] = []
	exception_sources: list[dict[str, Any]] = []
	counts: dict[str, int] = {}
	for row in timesheets:
		timesheet = frappe.get_doc("Timesheet", row.name)
		for detail in timesheet.get("time_logs") or []:
			work_date = _billing_date(detail, timesheet)
			if not work_date or not period_start <= work_date <= period_end:
				continue
			billing_hours = detail.get("billing_hours")
			if billing_hours is None:
				billing_hours = detail.get("hours") if detail.get("is_billable") else 0
			if float(billing_hours or 0) <= 0:
				continue
			status, context = _billing_status(detail, claimed_sources)
			source = _billing_source(detail, timesheet, status, context)
			if status == "Eligible":
				eligible_sources.append(source)
			else:
				exception_sources.append(source)
			counts[status] = counts.get(status, 0) + 1

	eligible_groups = _aggregate_billing_sources(eligible_sources)
	for item in eligible_groups:
		sources = item.pop("sources")
		review.append(
			"items",
			{
				**item,
				"timesheet": sources[0]["timesheet"],
				"timesheet_detail": sources[0]["timesheet_detail"] if len(sources) == 1 else None,
				"source_count": len(sources),
				"source_details_json": _json(sources),
			},
		)
	for item in exception_sources:
		sources = [{"timesheet": item["timesheet"], "timesheet_detail": item["timesheet_detail"]}]
		review.append(
			"items",
			{
				**item,
				"hours": _round_billable_hours(item["raw_billable_hours"]),
				"amount": 0,
				"source_count": 1,
				"source_details_json": _json(sources),
			},
		)
	result = {
		"source_counts": counts,
		"eligible_group_count": len(eligible_groups),
		"rounding_minutes": 15,
	}
	review.result_json = _json(result)
	review.insert(ignore_permissions=True)
	return {"name": review.name, "counts": counts, "eligible_group_count": len(eligible_groups)}


def _invoice_description(item: Any) -> str:
	parts = [f"Leistungszeit am {item.work_date}", f"Projekt {item.project}"]
	if item.task:
		parts.append(f"Aufgabe {item.task}")
	ticket_references = _document_value(item, "ticket_references")
	customer_description = _document_value(item, "customer_description")
	if ticket_references:
		parts.append(f"Ticket {ticket_references}")
	if customer_description:
		parts.append(customer_description)
	return " — ".join(parts)


def _sales_order_time_billing_row(sales_order: Any, item_code: str) -> Any:
	matching_rows = _matching_sales_order_items(sales_order, item_code)
	if len(matching_rows) != 1:
		frappe.throw(
			_("Sales Order {0} must contain exactly one row for time billing item {1}; found {2}.").format(
				_document_value(sales_order, "name"), item_code, len(matching_rows)
			)
		)
	row_name = _document_value(matching_rows[0], "name")
	if not row_name:
		frappe.throw(
			_("The time billing item row in Sales Order {0} has no stable reference.").format(
				_document_value(sales_order, "name")
			)
		)
	row = matching_rows[0]
	if _document_value(row, "uom") != "Hour":
		frappe.throw(
			_("The time billing item in Sales Order {0} must use UOM Hour.").format(
				_document_value(sales_order, "name")
			)
		)
	if _decimal(_document_value(row, "conversion_factor")) != Decimal("1"):
		frappe.throw(
			_("The time billing item in Sales Order {0} must use conversion factor 1.").format(
				_document_value(sales_order, "name")
			)
		)
	return row


def assert_timesheet_unclaimed(timesheet: Any) -> None:
	claimed = {}
	for item in frappe.get_all(
		"Billing Review Item", fields=["timesheet_detail", "source_details_json", "status"]
	):
		for source in _billing_source_references(item):
			claimed[source] = item.status
	conflicts = [detail.name for detail in timesheet.time_logs if str(detail.name) in claimed]
	if conflicts:
		frappe.throw(
			_("Working time can no longer be changed because billing already references: {0}").format(
				", ".join(conflicts)
			)
		)


@frappe.whitelist()
def create_billing_invoice_drafts(review_name: str) -> dict[str, Any]:
	_only_system_manager()
	# Serialize draft creation for this review. Client retries and concurrent
	# clicks must observe the first transaction instead of creating duplicate
	# Sales Invoices from the same Timesheet Details.
	frappe.db.sql(
		"select name from `tabBilling Review` where name=%s for update",
		(review_name,),
	)
	review = frappe.get_doc("Billing Review", review_name)
	if review.status in {"Draft Created", "Invoiced"}:
		invoices = sorted({item.sales_invoice for item in review.items if item.sales_invoice})
		if not invoices:
			frappe.throw(_("This billing review is marked as invoiced but has no linked Sales Invoices."))
		return {"name": review.name, "sales_invoices": invoices, "created": False}
	if review.status != "Preview":
		frappe.throw(_("Only a billing preview can create invoice drafts."))
	settings = _settings()
	if not settings.default_time_billing_item:
		frappe.throw(_("Set Default time billing item in Platform Operations Settings first."))
	eligible_items = [item for item in review.items if item.status == "Eligible"]
	if not eligible_items:
		frappe.throw(_("This billing preview has no eligible rows."))
	claimed_sources = _claimed_billing_sources(exclude_review=review.name)
	conflicts = sorted(
		set().union(*(_billing_source_references(item) for item in eligible_items)) & set(claimed_sources)
	)
	if conflicts:
		frappe.throw(
			_("Billing sources are already assigned to another draft or invoice: {0}").format(
				", ".join(conflicts)
			)
		)
	groups: dict[tuple[str, str], list[Any]] = {}
	for item in eligible_items:
		groups.setdefault((item.customer, item.sales_order), []).append(item)
	invoice_groups: list[tuple[str, str, list[Any], Any, str]] = []
	for (customer, sales_order_name), items in groups.items():
		sales_order = frappe.get_doc("Sales Order", sales_order_name)
		time_item_row = _sales_order_time_billing_row(sales_order, settings.default_time_billing_item)
		so_detail = str(_document_value(time_item_row, "name"))
		sales_order_rate = _decimal(_document_value(time_item_row, "rate"))
		if any(_decimal(item.rate) != sales_order_rate for item in items):
			frappe.throw(
				_("Billing Review rates must equal the Sales Order time item rate for {0}.").format(
					sales_order_name
				)
			)
		invoice_groups.append((customer, sales_order_name, items, sales_order, so_detail))
	invoices: list[str] = []
	for customer, sales_order_name, items, sales_order, so_detail in invoice_groups:
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
						"so_detail": so_detail,
						"description": _invoice_description(item),
					}
					for item in items
				],
			}
		)
		invoice.insert(ignore_permissions=True)
		invoices.append(invoice.name)
		for item in items:
			item.status = "Draft Created"
			item.sales_invoice = invoice.name
	review.created_invoice_count = len(invoices)
	review.status = "Draft Created"
	review.result_json = _json({"sales_invoices": invoices, "status": "Draft Created"})
	review.save(ignore_permissions=True)
	return {"name": review.name, "sales_invoices": invoices, "created": True}


@frappe.whitelist()
def finalize_billing_review(review_name: str) -> dict[str, Any]:
	"""Mark a billing review invoiced after its draft invoices were submitted manually."""
	_only_system_manager()
	review = frappe.get_doc("Billing Review", review_name)
	if review.status == "Invoiced":
		return {"name": review.name, "status": review.status}
	if review.status != "Draft Created":
		frappe.throw(_("Only a review with draft invoices can be finalized."))

	invoices = sorted({item.sales_invoice for item in review.items if item.sales_invoice})
	if not invoices:
		frappe.throw(_("This billing review has no linked Sales Invoices."))
	not_submitted = [
		invoice
		for invoice in invoices
		if int(frappe.db.get_value("Sales Invoice", invoice, "docstatus") or 0) != 1
	]
	if not_submitted:
		frappe.throw(
			_("Submit the linked Sales Invoices before finalizing this review: {0}").format(
				", ".join(not_submitted)
			)
		)

	for item in review.items:
		if item.status == "Draft Created":
			item.status = "Invoiced"
	review.status = "Invoiced"
	review.result_json = _json(
		{"sales_invoices": invoices, "status": "Invoiced", "finalized_at": _now().isoformat()}
	)
	review.save(ignore_permissions=True)
	return {"name": review.name, "status": review.status, "sales_invoices": invoices}
