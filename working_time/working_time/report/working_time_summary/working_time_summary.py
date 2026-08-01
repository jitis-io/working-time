# Copyright (c) 2023, ALYF GmbH and contributors
# For license information, please see license.txt

import frappe
from frappe.query_builder.functions import Sum

from working_time.permissions import require_employee_access

COLUMNS = [
	{
		"fieldname": "employee",
		"label": "Employee",
		"fieldtype": "Link",
		"options": "Employee",
	},
	{
		"fieldname": "total_working_time",
		"label": "Total Working Time",
		"fieldtype": "Duration",
		"hide_days": 1,
		"hide_seconds": 1,
	},
	{
		"fieldname": "total_project_time",
		"label": "Total Project Time",
		"fieldtype": "Duration",
		"hide_days": 1,
		"hide_seconds": 1,
	},
	{
		"fieldname": "total_break_time",
		"label": "Total Break Time",
		"fieldtype": "Duration",
		"hide_days": 1,
		"hide_seconds": 1,
	},
]


def execute(filters=None):
	filters = filters or {}
	working_time = frappe.qb.DocType("Working Time")
	employee = require_employee_access()
	query = (
		frappe.qb.from_(working_time)
		.select(
			working_time.employee,
			Sum(working_time.working_time).as_("total_working_time"),
			Sum(working_time.project_time).as_("total_project_time"),
			Sum(working_time.break_time).as_("total_break_time"),
		)
		.where(working_time.docstatus == 1)
		.where(working_time.date >= filters.get("from_date"))
		.where(working_time.date <= filters.get("to_date"))
	)
	if employee:
		query = query.where(working_time.employee == employee)

	data = query.groupby(working_time.employee).run(as_dict=True)
	return COLUMNS, data
