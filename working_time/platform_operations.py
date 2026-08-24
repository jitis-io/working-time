from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any

import frappe
from frappe import _

QUARTER_HOUR = Decimal("0.25")
CLAIMED_BILLING_STATUSES = ("Draft Created", "Invoiced", "Already Invoiced")


def _now() -> datetime:
	return datetime.now(UTC).replace(tzinfo=None)


def _only_system_manager() -> None:
	frappe.only_for("System Manager")


def _json(value: Any) -> str:
	return json.dumps(value or {}, default=str, sort_keys=True)


def _settings():
	return frappe.get_single("Working Time Settings")


def _matching_sales_order_items(sales_order: Any, item_code: str | None) -> list[Any]:
	if not item_code:
		return []
	return [
		row
		for row in (_document_value(sales_order, "items", []) or [])
		if _document_value(row, "item_code") == item_code
	]


def _document_value(document: Any, fieldname: str, default: Any = None) -> Any:
	if hasattr(document, "get"):
		return document.get(fieldname, default)
	return getattr(document, fieldname, default)


def _decimal(value: Any) -> Decimal:
	return Decimal(str(value or 0))


def _project_time_billable(project: Any) -> bool:
	return bool(int(_document_value(project, "time_billable") or 0))


def _is_canonical_customer_project(project: Any) -> bool:
	customer = _document_value(project, "customer")
	if not customer:
		return False
	return frappe.db.get_value("Customer", customer, "customer_project") == _document_value(project, "name")


def _sales_order_matches_project(sales_order: Any, project: Any) -> bool:
	"""Require one submitted Sales Order to belong to the exact billing context."""
	return bool(
		sales_order
		and _document_value(sales_order, "name") == _document_value(project, "sales_order")
		and int(_document_value(sales_order, "docstatus") or 0) == 1
		and _document_value(sales_order, "customer") == _document_value(project, "customer")
		and _document_value(sales_order, "company") == _document_value(project, "company")
		and _document_value(sales_order, "project") == _document_value(project, "name")
	)


def _sales_order_identity(name: str) -> Any:
	return frappe.db.get_value(
		"Sales Order",
		name,
		["name", "customer", "company", "project", "docstatus"],
		as_dict=True,
	)


def _require_sales_order_for_project(sales_order: Any, project: Any) -> None:
	if not _sales_order_matches_project(sales_order, project):
		frappe.throw(
			_(
				"Sales Order {0} no longer belongs to the submitted customer, company and project context."
			).format(_document_value(project, "sales_order") or _document_value(sales_order, "name") or "?")
		)


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


def _claimed_billing_sources(
	exclude_review: str | None = None, *, for_update: bool = False
) -> dict[str, str]:
	filters: dict[str, Any] = {"status": ["in", list(CLAIMED_BILLING_STATUSES)]}
	if exclude_review:
		filters["parent"] = ["!=", exclude_review]
	if for_update:
		status_placeholders = ", ".join(["%s"] * len(CLAIMED_BILLING_STATUSES))
		params: list[Any] = list(CLAIMED_BILLING_STATUSES)
		exclude_clause = ""
		if exclude_review:
			exclude_clause = "and parent != %s"
			params.append(exclude_review)
		items = frappe.db.sql(
			f"""
			select timesheet_detail, source_details_json, status
			from `tabBilling Review Item`
			where parenttype = 'Billing Review'
			and status in ({status_placeholders})
			{exclude_clause}
			order by name
			for update
			""",
			tuple(params),
			as_dict=True,
		)
	else:
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


def _native_sales_invoice_status(detail: Any) -> str | None:
	invoice = str(_document_value(detail, "sales_invoice") or "").strip()
	if not invoice:
		return None
	docstatus = frappe.db.get_value("Sales Invoice", invoice, "docstatus")
	if docstatus is not None and int(docstatus) == 0:
		return "Already Drafted"
	# A submitted, cancelled, missing or otherwise inconsistent native reference
	# must all fail closed. Only an explicitly cleared source can be billed again.
	return "Already Invoiced"


def _billing_status(detail: Any, claimed_sources: dict[str, str]) -> tuple[str, dict[str, Any]]:
	native_status = _native_sales_invoice_status(detail)
	if native_status:
		return native_status, {}
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
	if not _project_time_billable(project):
		return "Locked", {"project": project}
	if float(project.get("billing_rate") or 0) <= 0:
		return "Locked", {"project": project}
	is_canonical = _is_canonical_customer_project(project)
	sales_order = None if is_canonical else project.get("sales_order")
	if sales_order:
		if not _sales_order_matches_project(_sales_order_identity(sales_order), project):
			return "Missing Sales Order", {"project": project}
	elif not is_canonical:
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
		"customer_description": str(detail.get("customer_description") or "").strip(),
		"sales_order": context.get("sales_order"),
		"work_date": _billing_date(detail, timesheet),
		"actual_hours": float(detail.get("hours") or 0),
		"raw_billable_hours": float(billing_hours or 0),
		"rate": float((project.get("billing_rate") if project else 0) or 0),
		"status": status,
		"sales_invoice": _document_value(detail, "sales_invoice"),
	}


@frappe.whitelist(methods=["POST"])
def create_billing_review(period_start: str, period_end: str, project: str | None = None) -> dict[str, Any]:
	_only_system_manager()
	if period_start > period_end:
		frappe.throw(_("Period start must be before period end."))
	if project:
		frappe.get_doc("Project", project)
	review = frappe.get_doc(
		{
			"doctype": "Billing Review",
			"period_start": period_start,
			"period_end": period_end,
			"project": project,
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
			if project and detail.get("project") != project:
				continue
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
	parts = [f"IT-Leistung am {_document_value(item, 'work_date')}"]
	ticket_references = _document_value(item, "ticket_references")
	customer_description = str(_document_value(item, "customer_description") or "").strip()
	if ticket_references:
		parts.append(f"Support-Ticket {ticket_references}")
	if customer_description:
		parts.append(customer_description)
	return " - ".join(parts)


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


def _review_source_items(eligible_items: list[Any]) -> dict[str, Any]:
	"""Return one owning review item per exact source, rejecting ambiguous previews."""
	source_items: dict[str, Any] = {}
	for item in eligible_items:
		references = _billing_source_references(item)
		expected_count = int(_document_value(item, "source_count") or len(references))
		if not references or expected_count != len(references):
			frappe.throw(_("Billing Review row has incomplete or ambiguous Timesheet Detail references."))
		for reference in references:
			if reference in source_items:
				frappe.throw(
					_("Timesheet Detail {0} occurs more than once in this Billing Review.").format(reference)
				)
			source_items[reference] = item
	return source_items


def _lock_billing_sources(source_items: dict[str, Any]) -> dict[str, Any]:
	"""Lock exact source rows and revalidate their native billing state."""
	source_names = sorted(source_items)
	if not source_names:
		frappe.throw(_("This billing preview has no Timesheet Detail sources."))
	placeholders = ", ".join(["%s"] * len(source_names))
	rows = frappe.db.sql(
		f"""
		select name, parent, parenttype, docstatus, project, is_billable,
			billing_hours, sales_invoice, from_time, to_time, activity_type,
			customer_description, description, project_name
		from `tabTimesheet Detail`
		where name in ({placeholders})
		order by name
		for update
		""",
		tuple(source_names),
		as_dict=True,
	)
	locked = {str(row.name): row for row in rows}
	missing = sorted(set(source_names) - set(locked))
	if missing:
		frappe.throw(_("Billing sources no longer exist: {0}").format(", ".join(missing)))

	native_conflicts: list[str] = []
	for source_name in source_names:
		row = locked[source_name]
		item = source_items[source_name]
		if (
			_document_value(row, "parenttype") != "Timesheet"
			or int(_document_value(row, "docstatus") or 0) != 1
			or not int(_document_value(row, "is_billable") or 0)
			or _decimal(_document_value(row, "billing_hours")) <= 0
			or _document_value(row, "project") != _document_value(item, "project")
		):
			frappe.throw(
				_("Billing source {0} changed after the preview and must be reviewed again.").format(
					source_name
				)
			)
		invoice = str(_document_value(row, "sales_invoice") or "").strip()
		if invoice:
			native_conflicts.append(f"{source_name} ({invoice})")

	if native_conflicts:
		frappe.throw(
			_("Billing sources already have native Sales Invoice references: {0}").format(
				", ".join(native_conflicts)
			)
		)

	checked_items: set[int] = set()
	for item in source_items.values():
		if id(item) in checked_items:
			continue
		checked_items.add(id(item))
		references = _billing_source_references(item)
		current_hours = sum(
			(_decimal(_document_value(locked[reference], "billing_hours")) for reference in references),
			Decimal(0),
		)
		preview_hours = _document_value(item, "raw_billable_hours")
		if preview_hours is not None and current_hours != _decimal(preview_hours):
			frappe.throw(_("Billing hours changed after the preview for project {0}.").format(item.project))
	return locked


def _invoice_timesheet_rows(items: list[Any], locked_sources: dict[str, Any]) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for item in items:
		for source_name in sorted(_billing_source_references(item)):
			source = locked_sources[source_name]
			hours = _decimal(_document_value(source, "billing_hours"))
			rows.append(
				{
					"time_sheet": _document_value(source, "parent"),
					"timesheet_detail": source_name,
					"from_time": _document_value(source, "from_time"),
					"to_time": _document_value(source, "to_time"),
					"billing_hours": float(hours),
					"billing_amount": float(hours * _decimal(item.rate)),
					# Activity Type is an internal classification and is never part of
					# the customer-facing invoice evidence.
					"activity_type": None,
					# Freeze complete customer-facing evidence on the invoice. Never
					# fall back to the internal Timesheet Detail description.
					"description": _invoice_description(item),
					"working_time_customer_snapshot": 1,
					"project_name": _document_value(source, "project_name") or item.project,
				}
			)
	return rows


def _billing_review_invoices(review: Any) -> list[str]:
	return sorted(
		{
			str(_document_value(item, "sales_invoice"))
			for item in review.items
			if _document_value(item, "sales_invoice")
		}
	)


def _synchronize_billing_review_status(review: Any) -> dict[str, Any]:
	"""Derive review and row states from linked Sales Invoices, idempotently."""
	invoices = _billing_review_invoices(review)
	if not invoices:
		frappe.throw(_("This billing review has no linked Sales Invoices."))
	invoice_rows = frappe.get_all(
		"Sales Invoice",
		filters={"name": ["in", invoices]},
		fields=["name", "docstatus"],
	)
	docstatuses = {str(row.name): int(row.docstatus) for row in invoice_rows}
	invalid = [invoice for invoice in invoices if docstatuses.get(invoice) not in {0, 1}]

	changed = False
	for item in review.items:
		invoice = str(_document_value(item, "sales_invoice") or "")
		if not invoice:
			continue
		docstatus = docstatuses.get(invoice)
		if docstatus == 1:
			desired_item_status = "Invoiced"
		elif docstatus == 0:
			desired_item_status = "Draft Created"
		else:
			# Keep the source claimed when a linked invoice is missing or cancelled.
			desired_item_status = "Already Invoiced"
		if item.status != desired_item_status:
			item.status = desired_item_status
			changed = True

	if invalid:
		desired_status = "Failed"
		desired_error = _("Linked Sales Invoices are missing or cancelled: {0}").format(", ".join(invalid))
	elif all(docstatuses[invoice] == 1 for invoice in invoices):
		desired_status = "Invoiced"
		desired_error = ""
	else:
		desired_status = "Draft Created"
		desired_error = ""

	try:
		previous_result = json.loads(_document_value(review, "result_json") or "{}")
	except (TypeError, ValueError):
		previous_result = {}
	result = {"sales_invoices": invoices, "status": desired_status}
	if desired_status == "Invoiced":
		result["finalized_at"] = previous_result.get("finalized_at") or _now().isoformat()
	desired_result_json = _json(result)

	for fieldname, value in (
		("status", desired_status),
		("error", desired_error),
		("created_invoice_count", len(invoices)),
		("result_json", desired_result_json),
	):
		if _document_value(review, fieldname) != value:
			setattr(review, fieldname, value)
			changed = True
	if changed:
		review.save(ignore_permissions=True)
	return {
		"name": review.name,
		"status": desired_status,
		"sales_invoices": invoices,
		"error": desired_error,
	}


def synchronize_billing_reviews_for_invoice(doc: Any, method: str | None = None) -> None:
	"""Keep Billing Reviews aligned when a linked Sales Invoice is submitted or cancelled."""
	del method
	invoice_name = str(_document_value(doc, "name") or "").strip()
	if not invoice_name:
		return
	review_names = sorted(
		set(
			frappe.get_all(
				"Billing Review Item",
				filters={"sales_invoice": invoice_name},
				pluck="parent",
			)
		)
	)
	for review_name in review_names:
		frappe.db.sql(
			"select name from `tabBilling Review` where name=%s for update",
			(review_name,),
		)
		review = frappe.get_doc("Billing Review", review_name)
		_synchronize_billing_review_status(review)


def validate_billing_review_invoice_sources(doc: Any, method: str | None = None) -> None:
	"""Require linked invoice drafts to retain their exact, still-unbilled native sources."""
	del method
	invoice_name = str(_document_value(doc, "name") or "").strip()
	if not invoice_name:
		return
	review_items = frappe.get_all(
		"Billing Review Item",
		filters={"sales_invoice": invoice_name},
		fields=[
			"timesheet_detail",
			"source_details_json",
			"source_count",
			"project",
			"raw_billable_hours",
		],
	)
	if not review_items:
		return
	source_items = _review_source_items(review_items)
	locked_sources = _lock_billing_sources(source_items)
	actual_rows = [
		row
		for row in (_document_value(doc, "timesheets", []) or [])
		if _document_value(row, "timesheet_detail")
	]
	actual_references = [str(_document_value(row, "timesheet_detail")) for row in actual_rows]
	if len(actual_references) != len(set(actual_references)) or set(actual_references) != set(source_items):
		frappe.throw(_("Sales Invoice Timesheets no longer match the Billing Review sources."))
	for row in actual_rows:
		reference = str(_document_value(row, "timesheet_detail"))
		source = locked_sources[reference]
		if str(_document_value(row, "time_sheet") or "") != str(_document_value(source, "parent") or ""):
			frappe.throw(_("Sales Invoice Timesheet {0} references the wrong Timesheet.").format(reference))


@frappe.whitelist(methods=["POST"])
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
		frappe.throw(_("Set Default time billing item in Working Time Settings first."))
	eligible_items = [item for item in review.items if item.status == "Eligible"]
	if not eligible_items:
		frappe.throw(_("This billing preview has no eligible rows."))
	source_items = _review_source_items(eligible_items)
	# Different Billing Reviews can contain the same preview rows. Lock the
	# canonical Timesheet Details first, then use a current locking read for
	# claims so the transaction that loses the race observes the winner.
	locked_sources = _lock_billing_sources(source_items)
	claimed_sources = _claimed_billing_sources(exclude_review=review.name, for_update=True)
	conflicts = sorted(set(source_items) & set(claimed_sources))
	if conflicts:
		frappe.throw(
			_("Billing sources are already assigned to another draft or invoice: {0}").format(
				", ".join(conflicts)
			)
		)
	groups: dict[tuple[str, str | None], list[Any]] = {}
	project_context: dict[str, tuple[Any, bool]] = {}
	for item in eligible_items:
		if item.project not in project_context:
			project_doc = frappe.get_doc("Project", item.project)
			project_context[item.project] = (
				project_doc,
				_is_canonical_customer_project(project_doc),
			)
		project_doc, is_canonical = project_context[item.project]
		if (
			project_doc.customer != item.customer
			or not _project_time_billable(project_doc)
			or _decimal(project_doc.get("billing_rate")) != _decimal(item.rate)
		):
			frappe.throw(
				_("Project time billing settings changed after the preview for {0}.").format(item.project)
			)
		if is_canonical:
			sales_order_name = None
		elif not project_doc.get("sales_order") or item.sales_order != project_doc.get("sales_order"):
			frappe.throw(_("Project Sales Order changed after the preview for {0}.").format(item.project))
		else:
			sales_order_name = project_doc.get("sales_order")
		groups.setdefault((item.customer, sales_order_name), []).append(item)
	invoice_groups: list[dict[str, Any]] = []
	for (customer, sales_order_name), items in groups.items():
		if sales_order_name:
			sales_order = frappe.get_doc("Sales Order", sales_order_name)
			for item in items:
				_require_sales_order_for_project(sales_order, project_context[item.project][0])
			time_item_row = _sales_order_time_billing_row(sales_order, settings.default_time_billing_item)
			so_detail = str(_document_value(time_item_row, "name"))
			sales_order_rate = _decimal(_document_value(time_item_row, "rate"))
			if any(_decimal(item.rate) != sales_order_rate for item in items):
				frappe.throw(
					_("Billing Review rates must equal the Sales Order time item rate for {0}.").format(
						sales_order_name
					)
				)
			invoice_groups.append(
				{
					"customer": customer,
					"sales_order": sales_order_name,
					"items": items,
					"company": sales_order.company,
					"currency": sales_order.currency,
					"so_detail": so_detail,
				}
			)
			continue

		projects = {item.project: project_context[item.project][0] for item in items}
		companies = {project.company for project in projects.values() if project.company}
		if len(companies) != 1:
			frappe.throw(_("All customer projects in one invoice must use the same company."))
		company = companies.pop()
		currency = frappe.db.get_value("Company", company, "default_currency")
		if not currency:
			frappe.throw(
				_("Set a Default Currency for company {0} before creating invoice drafts.").format(company)
			)
		invoice_groups.append(
			{
				"customer": customer,
				"sales_order": None,
				"items": items,
				"company": company,
				"currency": currency,
				"so_detail": None,
			}
		)
	invoices: list[str] = []
	for group in invoice_groups:
		invoice_items = []
		for item in group["items"]:
			invoice_item = {
				"item_code": settings.default_time_billing_item,
				"qty": item.hours,
				"rate": item.rate,
				"project": item.project,
				"description": _invoice_description(item),
			}
			if group["sales_order"]:
				invoice_item.update({"sales_order": group["sales_order"], "so_detail": group["so_detail"]})
			invoice_items.append(invoice_item)
		invoice_values = {
			"doctype": "Sales Invoice",
			"customer": group["customer"],
			"company": group["company"],
			"items": invoice_items,
			"timesheets": _invoice_timesheet_rows(group["items"], locked_sources),
		}
		if group["currency"]:
			invoice_values["currency"] = group["currency"]
		invoice = frappe.get_doc(invoice_values)
		invoice.insert(ignore_permissions=True)
		invoices.append(invoice.name)
		for item in group["items"]:
			item.status = "Draft Created"
			item.sales_invoice = invoice.name
	review.created_invoice_count = len(invoices)
	review.status = "Draft Created"
	review.result_json = _json({"sales_invoices": invoices, "status": "Draft Created"})
	review.save(ignore_permissions=True)
	return {"name": review.name, "sales_invoices": invoices, "created": True}


@frappe.whitelist(methods=["POST"])
def create_project_time_invoice_draft(project: str, period_start: str, period_end: str) -> dict[str, Any]:
	"""Create exactly one draft invoice from one project's monthly preview."""
	_only_system_manager()
	project = str(project or "").strip()
	if not project:
		frappe.throw(_("Project is required for project time billing."))
	save_point = "project_time_invoice_draft"
	frappe.db.savepoint(save_point)
	try:
		review_result = create_billing_review(period_start, period_end, project=project)
		draft_result = create_billing_invoice_drafts(review_result["name"])
		invoices = list(draft_result.get("sales_invoices") or [])
		if len(invoices) != 1:
			frappe.throw(
				_("Project billing must create exactly one draft Sales Invoice; created {0}.").format(
					len(invoices)
				)
			)
		return {"review": review_result["name"], "sales_invoices": invoices}
	except Exception:
		frappe.db.rollback(save_point=save_point)
		raise


@frappe.whitelist(methods=["POST"])
def finalize_billing_review(review_name: str) -> dict[str, Any]:
	"""Mark a billing review invoiced after its draft invoices were submitted manually."""
	_only_system_manager()
	frappe.db.sql(
		"select name from `tabBilling Review` where name=%s for update",
		(review_name,),
	)
	review = frappe.get_doc("Billing Review", review_name)
	if review.status == "Invoiced":
		return {
			"name": review.name,
			"status": review.status,
			"sales_invoices": _billing_review_invoices(review),
		}
	if review.status not in {"Draft Created", "Failed"}:
		frappe.throw(_("Only a review with draft invoices can be finalized."))

	result = _synchronize_billing_review_status(review)
	if result["status"] == "Invoiced":
		return result
	if result["status"] == "Failed":
		return result
	invoices = result["sales_invoices"]
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

	frappe.throw(_("The linked Sales Invoices could not be finalized."))
