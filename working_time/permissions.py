import frappe
from frappe import _

TECHNICAL_SERVICE_ROLES = frozenset(
	{
		"JITIS Portal ERP Reader",
		"JITIS Portal Helpdesk Integration",
		"JITIS Portal Wiki Reader",
	}
)


def is_time_booking_identity(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	if frappe.db.get_value("User", user, "user_type") == "Website User":
		return False
	return not TECHNICAL_SERVICE_ROLES.intersection(frappe.get_roles(user))


def require_time_booking_identity(user: str | None = None) -> str:
	user = user or frappe.session.user
	if not is_time_booking_identity(user):
		frappe.throw(
			_("Website and technical service identities may not book working time."),
			frappe.PermissionError,
		)
	return user


def is_system_manager(user: str | None = None) -> bool:
	"""Return whether the user may access every Working Time record."""
	user = user or frappe.session.user
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def get_user_employee(user: str | None = None) -> str | None:
	"""Return the Employee explicitly linked to the user, if one exists."""
	user = user or frappe.session.user
	if not is_time_booking_identity(user):
		return None
	return frappe.db.get_value("Employee", {"user_id": user}, "name")


def require_employee_access(employee: str | None = None, user: str | None = None) -> str | None:
	"""Resolve an allowed Employee or raise without disclosing another employee's data."""
	user = require_time_booking_identity(user)
	if is_system_manager(user):
		return employee

	user_employee = get_user_employee(user)
	if not user_employee:
		frappe.throw(
			_("Your user account is not linked to an Employee record."),
			frappe.PermissionError,
		)

	if employee and employee != user_employee:
		frappe.throw(
			_("You may only access your own Working Time records."),
			frappe.PermissionError,
		)

	return user_employee


def working_time_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	"""Restrict list and get_list queries to the user's linked Employee."""
	del doctype
	user = user or frappe.session.user
	if not is_time_booking_identity(user):
		return "1=0"
	if is_system_manager(user):
		return ""

	employee = get_user_employee(user)
	if not employee:
		return "1=0"

	return f"`tabWorking Time`.`employee` = {frappe.db.escape(employee)}"


def working_time_has_permission(doc, ptype: str, user: str | None = None, debug: bool = False) -> bool:
	"""Allow every document operation only for the user's linked Employee."""
	del ptype, debug
	user = user or frappe.session.user
	if not is_time_booking_identity(user):
		return False
	if is_system_manager(user):
		return True

	employee = get_user_employee(user)
	if not employee or not doc:
		return False

	doc_employee = doc.get("employee") if hasattr(doc, "get") else getattr(doc, "employee", None)
	return doc_employee == employee
