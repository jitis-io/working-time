from working_time.install import make_custom_fields


def execute() -> None:
	# Ensure the Issue field on ERPNext's Timesheet Detail exists before the
	# platform integration migrates Helpdesk ticket references later in the same
	# site migration.
	make_custom_fields()
