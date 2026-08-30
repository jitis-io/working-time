from __future__ import annotations

from typing import Any

import frappe
from frappe import _


def _document_value(doc: Any, fieldname: str, default: Any = None) -> Any:
	if isinstance(doc, dict):
		return doc.get(fieldname, default)
	getter = getattr(doc, "get", None)
	if callable(getter):
		return getter(fieldname, default=default)
	return getattr(doc, fieldname, default)


def _set_document_value(doc: Any, fieldname: str, value: Any) -> None:
	if isinstance(doc, dict):
		doc[fieldname] = value
	else:
		setattr(doc, fieldname, value)


def _as_bool(value: Any) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)


def _require_permission(doctype: str, permission_type: str, doc: Any | None = None) -> None:
	if frappe.has_permission(doctype, permission_type, doc=doc):
		return
	frappe.throw(
		_("You are not permitted to {0} {1} records.").format(permission_type, doctype),
		frappe.PermissionError,
	)


def _default_company() -> str | None:
	return frappe.db.get_single_value("Global Defaults", "default_company")


def _load_linked_project(customer_doc: Any) -> Any | None:
	project_name = _document_value(customer_doc, "customer_project")
	if not project_name:
		return None
	project_name = frappe.db.get_value(
		"Project",
		{"name": project_name, "customer": customer_doc.name},
		"name",
	)
	if not project_name:
		return None
	project = frappe.get_doc("Project", project_name)
	return None if _document_value(project, "status") == "Cancelled" else project


def _load_exact_customer_project(customer_name: str) -> Any | None:
	project_name = frappe.db.get_value(
		"Project",
		{"project_name": customer_name, "customer": customer_name},
		"name",
	)
	return frappe.get_doc("Project", project_name) if project_name else None


def _project_name_conflict(customer_name: str) -> Any | None:
	return frappe.db.get_value(
		"Project",
		{"project_name": customer_name},
		["name", "customer"],
		as_dict=True,
	)


def _preflight_project_name_conflicts(customers: list[str]) -> None:
	"""Reject deterministic blockers before the first backfill write."""

	for customer in customers:
		customer_doc = frappe.get_doc("Customer", customer)
		project = _load_linked_project(customer_doc) or _load_exact_customer_project(customer)
		if project:
			if _document_value(project, "status") == "Cancelled":
				frappe.throw(
					_("Project {0} is cancelled and cannot be used as the customer project.").format(
						project.name
					)
				)
			continue

		conflict = _project_name_conflict(customer)
		if conflict and _document_value(conflict, "customer") != customer:
			frappe.throw(
				_("Project name {0} is already used by project {1} for another customer.").format(
					customer,
					_document_value(conflict, "name"),
				)
			)


def _needs_reactivation(project: Any) -> bool:
	return (
		_document_value(project, "status") in {"Completed", "On hold"}
		or _document_value(project, "is_active") != "Yes"
	)


def _normalize_customer_project(project: Any) -> bool:
	reopened = _needs_reactivation(project)
	values = {}
	if _document_value(project, "status") in {"Completed", "On hold"}:
		values["status"] = "Open"
	if _document_value(project, "is_active") != "Yes":
		values["is_active"] = "Yes"
	if _document_value(project, "percent_complete_method", "Manual") != "Manual":
		values["percent_complete_method"] = "Manual"
	if float(_document_value(project, "percent_complete", 0) or 0):
		values["percent_complete"] = 0
	if not values:
		return False
	frappe.db.set_value("Project", project.name, values)
	for fieldname, value in values.items():
		_set_document_value(project, fieldname, value)
	return reopened


def _link_customer_project(customer_doc: Any, project_name: str) -> None:
	if _document_value(customer_doc, "customer_project") == project_name:
		return
	frappe.db.set_value(
		"Customer",
		customer_doc.name,
		"customer_project",
		project_name,
		update_modified=False,
	)
	_set_document_value(customer_doc, "customer_project", project_name)


def _ensure_customer_project(customer: str, *, ignore_permissions: bool) -> dict[str, Any]:
	"""Return the single mapped customer-account project, creating it if needed.

	The Customer row lock serializes the lookup, creation and mapping. Only an
	already linked project or the exact ``Customer.name`` project is eligible for
	reuse; unrelated historical projects are deliberately left untouched.
	"""
	customer = str(customer or "").strip()
	if not customer:
		frappe.throw(_("Customer is required."))

	frappe.db.sql("select name from `tabCustomer` where name=%s for update", (customer,))
	customer_doc = frappe.get_doc("Customer", customer)
	if not ignore_permissions:
		_require_permission("Customer", "read", customer_doc)
		_require_permission("Customer", "write", customer_doc)

	project = _load_linked_project(customer_doc)
	if not project:
		project = _load_exact_customer_project(customer_doc.name)

	created = False
	reopened = False
	if project:
		if not ignore_permissions:
			_require_permission("Project", "read", project)
		if _document_value(project, "status") == "Cancelled":
			frappe.throw(
				_("Project {0} is cancelled and cannot be used as the customer project.").format(project.name)
			)
		needs_normalization = (
			_needs_reactivation(project)
			or _document_value(project, "percent_complete_method", "Manual") != "Manual"
			or bool(float(_document_value(project, "percent_complete", 0) or 0))
		)
		if needs_normalization and not ignore_permissions:
			_require_permission("Project", "write", project)
		reopened = _normalize_customer_project(project)
	else:
		conflict = _project_name_conflict(customer_doc.name)
		if conflict:
			frappe.throw(
				_("Project name {0} is already used by project {1} for another customer.").format(
					customer_doc.name,
					_document_value(conflict, "name"),
				)
			)
		company = _default_company()
		if not company:
			frappe.throw(_("Set a Default Company before creating customer projects."))
		if not ignore_permissions:
			_require_permission("Project", "create")
		project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": customer_doc.name,
				"company": company,
				"customer": customer_doc.name,
				"status": "Open",
				"is_active": "Yes",
				"percent_complete_method": "Manual",
				"percent_complete": 0,
				"time_billable": 0,
				"billing_model": "Non-billable",
			}
		)
		project.insert(ignore_permissions=ignore_permissions)
		created = True

	_link_customer_project(customer_doc, project.name)
	return {"project": project.name, "created": created, "reopened": reopened}


@frappe.whitelist(methods=["POST"])
def ensure_customer_project(customer: str) -> dict[str, Any]:
	"""Permission-checked API for provisioning or retrieving a customer project."""
	return _ensure_customer_project(customer, ignore_permissions=False)


def backfill_customer_projects() -> dict[str, int | bool]:
	"""Map all enabled customers in one transaction.

	A missing Default Company is detected before the first Customer is touched,
	so migrations can safely skip an unconfigured site without a partial map.
	Other failures are intentionally allowed to abort the surrounding Frappe
	transaction.
	"""
	if not _default_company():
		return {"processed": 0, "created": 0, "reopened": 0, "skipped": True}

	customers = frappe.get_all(
		"Customer",
		filters={"disabled": 0},
		pluck="name",
		order_by="name asc",
		limit_page_length=0,
	)
	_preflight_project_name_conflicts(customers)
	results = [_ensure_customer_project(customer, ignore_permissions=True) for customer in customers]
	return {
		"processed": len(results),
		"created": sum(bool(result["created"]) for result in results),
		"reopened": sum(bool(result["reopened"]) for result in results),
		"skipped": False,
	}


def backfill_issue_projects() -> dict[str, int]:
	"""Set the canonical customer project on every unmapped customer Issue."""
	issues = frappe.get_all(
		"Issue",
		filters={
			"customer": ("is", "set"),
			"project": ("is", "not set"),
		},
		fields=["name", "customer"],
		order_by="name asc",
		limit_page_length=0,
	)
	updated = 0
	for issue in issues:
		project = frappe.db.get_value(
			"Customer",
			_document_value(issue, "customer"),
			"customer_project",
		)
		if not project:
			continue
		if frappe.db.get_value("Project", project, "customer") != _document_value(issue, "customer"):
			continue
		frappe.db.set_value(
			"Issue",
			_document_value(issue, "name"),
			"project",
			project,
			update_modified=False,
		)
		updated += 1
	return {"matched": len(issues), "updated": updated, "skipped": len(issues) - updated}


def _issue_project_and_customer(issue: str) -> tuple[str | None, str | None]:
	state = frappe.db.get_value("Issue", issue, ["project", "customer"], as_dict=True)
	if not state:
		return None, None

	customer = _document_value(state, "customer")
	project = _document_value(state, "project")
	if not project and customer:
		project = frappe.db.get_value("Customer", customer, "customer_project")
	return project, customer


def assign_issue_project_to_task(doc: Any, method: str | None = None) -> None:
	"""Keep a Task linked to the same canonical project as its Issue."""

	del method
	issue = _document_value(doc, "issue")
	if not issue:
		return

	expected_project, customer = _issue_project_and_customer(issue)
	project = _document_value(doc, "project")
	if expected_project:
		if project and project != expected_project:
			frappe.throw(_("Task and issue must belong to the same project."))
		if not project:
			project = expected_project
			_set_document_value(doc, "project", project)

	if project and customer:
		project_customer = frappe.db.get_value("Project", project, "customer")
		if project_customer != customer:
			frappe.throw(_("Issue and project must belong to the same customer."))


def backfill_task_projects() -> dict[str, int]:
	"""Set the Issue project on open, non-template Tasks that have no project."""

	tasks = frappe.get_all(
		"Task",
		filters={
			"status": ("not in", ("Completed", "Cancelled")),
			"is_template": 0,
			"issue": ("is", "set"),
			"project": ("is", "not set"),
		},
		fields=["name", "issue"],
		order_by="name asc",
		limit_page_length=0,
	)
	updated = 0
	for task in tasks:
		project, customer = _issue_project_and_customer(_document_value(task, "issue"))
		if not project:
			continue
		if customer and frappe.db.get_value("Project", project, "customer") != customer:
			continue
		frappe.db.set_value(
			"Task",
			_document_value(task, "name"),
			"project",
			project,
			update_modified=False,
		)
		updated += 1
	return {"matched": len(tasks), "updated": updated, "skipped": len(tasks) - updated}


def after_customer_insert(doc: Any, method: str | None = None) -> None:
	del method
	if _as_bool(_document_value(doc, "disabled")):
		return
	_ensure_customer_project(doc.name, ignore_permissions=True)


def after_customer_update(doc: Any, method: str | None = None) -> None:
	"""Provision the account immediately when an existing Customer is enabled."""

	del method
	if _as_bool(_document_value(doc, "disabled")):
		return
	get_doc_before_save = getattr(doc, "get_doc_before_save", None)
	if callable(get_doc_before_save) and get_doc_before_save() is None:
		# New Customers are handled exactly once by after_customer_insert.
		return
	has_value_changed = getattr(doc, "has_value_changed", None)
	if callable(has_value_changed) and has_value_changed("disabled"):
		_ensure_customer_project(doc.name, ignore_permissions=True)


def assign_customer_project_to_issue(doc: Any, method: str | None = None) -> None:
	del method
	customer = _document_value(doc, "customer")
	if not customer:
		return

	project = _document_value(doc, "project")
	if not project:
		project = frappe.db.get_value("Customer", customer, "customer_project")
		if project:
			_set_document_value(doc, "project", project)
	if not project:
		return

	project_customer = frappe.db.get_value("Project", project, "customer")
	if project_customer != customer:
		frappe.throw(_("Issue and project must belong to the same customer."))


def protect_customer_account_project(doc: Any, method: str | None = None) -> None:
	"""Keep the canonical customer account open and replace Frappe's raw link error."""

	customer = _document_value(doc, "customer")
	get_before_save = getattr(doc, "get_doc_before_save", None)
	previous = get_before_save() if callable(get_before_save) else None
	previous_customer = _document_value(previous, "customer") if previous else None
	if previous and previous_customer != customer:
		if (
			previous_customer
			and frappe.db.get_value("Customer", previous_customer, "customer_project") == doc.name
		):
			frappe.throw(_("The customer of a permanent customer account cannot be changed."))
		if any(
			frappe.db.exists(doctype, {"project": doc.name})
			for doctype in (
				"Issue",
				"Task",
				"Working Time Log",
				"Timesheet Detail",
				"Sales Order",
				"Sales Invoice Item",
				"Purchase Invoice Item",
			)
		):
			frappe.throw(
				_("The customer cannot be changed after work or billing records reference this project.")
			)
	if not customer:
		return
	linked_project = frappe.db.get_value("Customer", customer, "customer_project")
	if linked_project != _document_value(doc, "name"):
		return
	status = _document_value(doc, "status")
	is_active = _document_value(doc, "is_active", "Yes")
	if method != "on_trash" and status == "Open" and is_active == "Yes":
		return
	frappe.throw(
		_(
			"Project {0} is the permanent customer account for {1} and must remain open and active. "
			"If the link is wrong, correct the customer project on the Customer first."
		).format(_document_value(doc, "name"), customer),
		frappe.ValidationError,
	)


def sync_project_time_billing(doc: Any, method: str | None = None) -> None:
	"""Keep the hidden legacy model aligned with the simple visible time switch."""

	del method
	if _as_bool(_document_value(doc, "time_billable")):
		_set_document_value(doc, "billing_model", "Time and Material")
	elif _document_value(doc, "billing_model") == "Time and Material":
		_set_document_value(doc, "billing_model", "Non-billable")


def apply_invoice_project(doc: Any, method: str | None = None) -> None:
	"""Copy a header Project only to invoice rows that do not have their own Project."""

	del method
	project = _document_value(doc, "project")
	if not project:
		return
	for item in _document_value(doc, "items", []) or []:
		if not _document_value(item, "project"):
			_set_document_value(item, "project", project)
