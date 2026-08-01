import frappe

from working_time.permissions import get_user_employee, is_system_manager, require_employee_access


@frappe.whitelist()
def get_employee_working_hours(employee: str):
	"""Return the average daily working time calculated from the employee's weekly hours."""
	if not isinstance(employee, str):
		raise ValueError("Employee should be a string")

	if not employee:
		return None
	employee = require_employee_access(employee)
	frappe.has_permission("Employee", "read", employee, throw=True)
	working_hours_per_week = frappe.get_value("Employee", employee, "working_hours_per_week")
	if working_hours_per_week:
		return working_hours_per_week / 5


@frappe.whitelist()
def get_employee_name():
	if is_system_manager():
		return get_user_employee()
	return require_employee_access()
