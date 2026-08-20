from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe
from frappe import _
from frappe.utils import nowdate

from working_time.permissions import get_user_employee, is_system_manager
from working_time.platform_operations import _claimed_billing_sources

MONTH_PATTERN = re.compile(r"\A\d{4}-(?:0[1-9]|1[0-2])\Z")
ROW_LIMIT = 8
OPEN_ISSUE_STATUSES = ("Open", "Replied", "On Hold")
OPEN_TASK_STATUSES = ("Open", "Working", "Pending Review", "Overdue")


def _value(row: Any, fieldname: str, default: Any = None) -> Any:
	if isinstance(row, Mapping):
		return row.get(fieldname, default)
	if hasattr(row, "get"):
		return row.get(fieldname, default)
	return getattr(row, fieldname, default)


def _decimal(value: Any) -> Decimal:
	try:
		return Decimal(str(value or 0))
	except (InvalidOperation, TypeError, ValueError):
		return Decimal(0)


def _number(value: Any) -> float:
	return float(_decimal(value))


def _date_string(value: Any) -> str | None:
	if not value:
		return None
	if hasattr(value, "date") and not isinstance(value, date):
		value = value.date()
	if hasattr(value, "isoformat"):
		return str(value.isoformat())[:10]
	return str(value)[:10]


def _month_period(month: str | None = None, *, today: date | None = None) -> dict[str, Any]:
	"""Return strict, single-calendar-month bounds for SQL and the API response."""
	if month is None:
		selected = (today or date.fromisoformat(nowdate())).strftime("%Y-%m")
	else:
		selected = str(month).strip()
	if not MONTH_PATTERN.fullmatch(selected):
		frappe.throw(_("Month must use the YYYY-MM format."), frappe.ValidationError)

	try:
		start = date.fromisoformat(f"{selected}-01")
		next_start = date(start.year + (start.month == 12), (start.month % 12) + 1, 1)
	except (OverflowError, ValueError):
		frappe.throw(_("Month must use the YYYY-MM format."), frappe.ValidationError)
		raise AssertionError("frappe.throw must raise") from None

	return {
		"month": selected,
		"start": start,
		"end": next_start - timedelta(days=1),
		"next_start": next_start,
	}


def _time_entry_rows(project: str, period: Mapping[str, Any]) -> list[Any]:
	return frappe.db.sql(
		"""
		select
			td.name,
			td.parent as timesheet,
			td.from_time,
			ts.employee,
			ts.employee_name,
			td.activity_type,
			td.issue,
			td.task,
			td.description,
			td.hours,
			case
				when td.billing_hours is not null then td.billing_hours
				when td.is_billable = 1 then td.hours
				else 0
			end as billable_hours,
			coalesce(td.base_costing_amount, 0) as cost,
			coalesce(td.base_billing_amount, 0) as billable_amount,
			td.sales_invoice
		from `tabTimesheet Detail` td
		inner join `tabTimesheet` ts on ts.name = td.parent
		where ts.docstatus = 1
			and td.project = %(project)s
			and td.from_time >= %(start)s
			and td.from_time < %(next_start)s
		order by td.from_time desc, td.name desc
		""",
		{
			"project": project,
			"start": period["start"],
			"next_start": period["next_start"],
		},
		as_dict=True,
	)


def _purchase_invoice_item_rows(project: str, company: str, period: Mapping[str, Any]) -> list[Any]:
	return frappe.db.sql(
		"""
		select
			pi.name,
			pi.posting_date,
			pi.supplier,
			pi.supplier_name,
			pi.status,
			pi.docstatus,
			pi.is_return,
			pi.modified,
			pii.idx as item_idx,
			pii.base_net_amount as amount
		from `tabPurchase Invoice Item` pii
		inner join `tabPurchase Invoice` pi on pi.name = pii.parent
		where pi.docstatus in (0, 1)
			and pi.company = %(company)s
			and coalesce(nullif(pii.project, ''), pi.project) = %(project)s
			and pi.posting_date >= %(start)s
			and pi.posting_date < %(next_start)s
		order by pi.posting_date desc, pi.modified desc, pi.name desc, pii.idx asc
		""",
		{
			"project": project,
			"company": company,
			"start": period["start"],
			"next_start": period["next_start"],
		},
		as_dict=True,
	)


def _sales_invoice_item_rows(project: str, company: str, period: Mapping[str, Any]) -> list[Any]:
	return frappe.db.sql(
		"""
		select
			si.name,
			si.posting_date,
			si.customer,
			si.customer_name,
			si.status,
			si.docstatus,
			si.is_return,
			si.modified,
			sii.idx as item_idx,
			sii.base_net_amount as amount
		from `tabSales Invoice Item` sii
		inner join `tabSales Invoice` si on si.name = sii.parent
		where si.docstatus in (0, 1)
			and si.company = %(company)s
			and coalesce(nullif(sii.project, ''), si.project) = %(project)s
			and si.posting_date >= %(start)s
			and si.posting_date < %(next_start)s
		order by si.posting_date desc, si.modified desc, si.name desc, sii.idx asc
		""",
		{
			"project": project,
			"company": company,
			"start": period["start"],
			"next_start": period["next_start"],
		},
		as_dict=True,
	)


def _aggregate_time_rows(
	rows: list[Any], claimed_sources: Mapping[str, str]
) -> tuple[dict[str, float], list[dict[str, Any]]]:
	totals = {
		"hours": Decimal(0),
		"billable_hours": Decimal(0),
		"unbilled_hours": Decimal(0),
		"time_cost": Decimal(0),
		"billable_amount": Decimal(0),
		"unbilled_amount": Decimal(0),
	}
	entries: list[dict[str, Any]] = []
	for row in rows:
		hours = _decimal(_value(row, "hours"))
		billable_hours = _decimal(_value(row, "billable_hours"))
		cost = _decimal(_value(row, "cost"))
		billable_amount = _decimal(_value(row, "billable_amount"))
		is_unbilled = (
			billable_hours > 0
			and not _value(row, "sales_invoice")
			and str(_value(row, "name")) not in claimed_sources
		)
		unbilled_hours = billable_hours if is_unbilled else Decimal(0)
		unbilled_amount = billable_amount if is_unbilled else Decimal(0)

		totals["hours"] += hours
		totals["billable_hours"] += billable_hours
		totals["unbilled_hours"] += unbilled_hours
		totals["time_cost"] += cost
		totals["billable_amount"] += billable_amount
		totals["unbilled_amount"] += unbilled_amount
		entries.append(
			{
				"name": _value(row, "name"),
				"timesheet": _value(row, "timesheet"),
				"date": _date_string(_value(row, "from_time")),
				"employee": _value(row, "employee"),
				"employee_name": _value(row, "employee_name"),
				"activity_type": _value(row, "activity_type"),
				"issue": _value(row, "issue"),
				"task": _value(row, "task"),
				"description": str(_value(row, "description") or ""),
				"hours": float(hours),
				"billable_hours": float(billable_hours),
				"unbilled_hours": float(unbilled_hours),
				"cost": float(cost),
				"billable_amount": float(billable_amount),
				"unbilled_amount": float(unbilled_amount),
				"sales_invoice": _value(row, "sales_invoice"),
			}
		)
	return ({fieldname: float(value) for fieldname, value in totals.items()}, entries)


def _aggregate_invoice_rows(
	rows: list[Any], *, party_field: str, party_name_field: str
) -> list[dict[str, Any]]:
	"""Collapse matching invoice items into one row per parent without changing signs."""
	grouped: dict[str, dict[str, Any]] = {}
	amounts: dict[str, Decimal] = {}
	for row in rows:
		name = str(_value(row, "name") or "")
		if not name:
			continue
		if name not in grouped:
			docstatus = int(_value(row, "docstatus") or 0)
			grouped[name] = {
				"name": name,
				"posting_date": _date_string(_value(row, "posting_date")),
				party_field: _value(row, party_field),
				party_name_field: _value(row, party_name_field),
				"status": _value(row, "status") or ("Draft" if docstatus == 0 else "Submitted"),
				"docstatus": docstatus,
				"is_return": bool(_value(row, "is_return")),
			}
			amounts[name] = Decimal(0)
		amounts[name] += _decimal(_value(row, "amount"))

	result = []
	for name, invoice in grouped.items():
		result.append({**invoice, "amount": float(amounts[name])})
	return result


def _permitted_invoice_rows(doctype: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return [row for row in rows if frappe.has_permission(doctype, "read", doc=row["name"])]


def _permitted_time_rows(rows: list[Any]) -> list[Any]:
	permissions: dict[str, bool] = {}
	visible: list[Any] = []
	for row in rows:
		timesheet = str(_value(row, "timesheet") or "")
		if not timesheet:
			continue
		if timesheet not in permissions:
			permissions[timesheet] = bool(frappe.has_permission("Timesheet", "read", doc=timesheet))
		if permissions[timesheet]:
			visible.append(row)
	return visible


def _visible_count(doctype: str, project: str, statuses: tuple[str, ...]) -> int:
	if not frappe.has_permission(doctype, "read"):
		return 0
	try:
		return len(
			frappe.get_list(
				doctype,
				filters={"project": project, "status": ["in", list(statuses)]},
				fields=["name"],
				limit_page_length=0,
			)
		)
	except frappe.PermissionError:
		return 0


def _project_accepts_time_booking(project: Any) -> bool:
	return (
		_value(project, "status") not in {"Completed", "Cancelled"} and _value(project, "is_active") != "No"
	)


@frappe.whitelist()
def get_project_month(project: str, month: str | None = None) -> dict[str, Any]:
	project = str(project or "").strip()
	if not project:
		frappe.throw(_("Select a project."), frappe.ValidationError)
	period = _month_period(month)
	project_doc = frappe.get_doc("Project", project)
	if not frappe.has_permission("Project", "read", doc=project_doc):
		frappe.throw(_("You are not permitted to read this project."), frappe.PermissionError)

	company = project_doc.get("company")
	currency = frappe.db.get_value("Company", company, "default_currency") if company else None
	system_manager = bool(is_system_manager())
	can_view_time = system_manager or bool(frappe.has_permission("Timesheet", "read"))
	can_view_purchases = bool(frappe.has_permission("Purchase Invoice", "read"))
	can_view_sales = bool(frappe.has_permission("Sales Invoice", "read"))
	capabilities = {
		"can_book_time": _project_accepts_time_booking(project_doc)
		and bool(get_user_employee())
		and bool(frappe.has_permission("Working Time", "create")),
		"can_view_purchases": can_view_purchases,
		"can_view_sales": can_view_sales,
		"can_create_billing_review": system_manager
		and bool(frappe.has_permission("Billing Review", "create")),
	}

	time_rows: list[Any] = []
	if can_view_time:
		time_rows = _time_entry_rows(project_doc.name, period)
		if not system_manager:
			time_rows = _permitted_time_rows(time_rows)
	time_summary, time_entries = _aggregate_time_rows(
		time_rows, _claimed_billing_sources() if time_rows else {}
	)
	purchase_invoices: list[dict[str, Any]] = []
	if can_view_purchases and company:
		purchase_invoices = _permitted_invoice_rows(
			"Purchase Invoice",
			_aggregate_invoice_rows(
				_purchase_invoice_item_rows(project_doc.name, company, period),
				party_field="supplier",
				party_name_field="supplier_name",
			),
		)
	sales_invoices: list[dict[str, Any]] = []
	if can_view_sales and company:
		sales_invoices = _permitted_invoice_rows(
			"Sales Invoice",
			_aggregate_invoice_rows(
				_sales_invoice_item_rows(project_doc.name, company, period),
				party_field="customer",
				party_name_field="customer_name",
			),
		)

	purchase_cost = sum(
		(_decimal(row["amount"]) for row in purchase_invoices if row["docstatus"] == 1),
		start=Decimal(0),
	)
	sales_invoiced = sum(
		(_decimal(row["amount"]) for row in sales_invoices if row["docstatus"] == 1),
		start=Decimal(0),
	)
	sales_draft = sum(
		(_decimal(row["amount"]) for row in sales_invoices if row["docstatus"] == 0),
		start=Decimal(0),
	)
	time_cost = _decimal(time_summary["time_cost"])

	return {
		"project": {
			"name": project_doc.name,
			"project_name": project_doc.get("project_name"),
			"customer": project_doc.get("customer"),
			"company": company,
			"time_billable": bool(_decimal(project_doc.get("time_billable"))),
			"billing_rate": _number(project_doc.get("billing_rate")),
			"currency": currency,
		},
		"period": {
			"month": period["month"],
			"start": period["start"].isoformat(),
			"end": period["end"].isoformat(),
		},
		"capabilities": capabilities,
		"summary": {
			**time_summary,
			"purchase_cost": float(purchase_cost),
			"sales_invoiced": float(sales_invoiced),
			"sales_draft": float(sales_draft),
			"margin": float(sales_invoiced - purchase_cost - time_cost),
		},
		"counts": {
			"open_issues": _visible_count("Issue", project_doc.name, OPEN_ISSUE_STATUSES),
			"open_tasks": _visible_count("Task", project_doc.name, OPEN_TASK_STATUSES),
			"purchase_invoices": len(purchase_invoices),
			"sales_invoices": len(sales_invoices),
		},
		"rows": {
			"time_entries": time_entries[:ROW_LIMIT],
			"purchase_invoices": purchase_invoices[:ROW_LIMIT],
			"sales_invoices": sales_invoices[:ROW_LIMIT],
		},
	}
