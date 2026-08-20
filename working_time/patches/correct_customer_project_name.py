import frappe

PROJECT = "P-2510-0001"
CUSTOMER = "K-2601008"
WRONG_PROJECT_NAME = "K-2601013"
CORRECT_PROJECT_NAME = CUSTOMER


def execute():
	"""Correct the verified JITIS display-name mismatch before customer-account backfill."""

	state = frappe.db.get_value(
		"Project",
		PROJECT,
		["project_name", "customer"],
		as_dict=True,
	)
	if not state or state.customer != CUSTOMER or state.project_name == CORRECT_PROJECT_NAME:
		return
	if state.project_name != WRONG_PROJECT_NAME:
		return

	conflict = frappe.db.get_value(
		"Project",
		{"project_name": CORRECT_PROJECT_NAME, "name": ("!=", PROJECT)},
		"name",
	)
	if conflict:
		frappe.throw(
			f"Cannot correct {PROJECT}: project name {CORRECT_PROJECT_NAME} is already used by {conflict}."
		)

	frappe.db.set_value(
		"Project",
		PROJECT,
		"project_name",
		CORRECT_PROJECT_NAME,
		update_modified=False,
	)
