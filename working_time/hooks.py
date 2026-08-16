app_name = "working_time"
app_title = "Working Time"
app_publisher = "ALYF GmbH and JITIS contributors"
app_description = "Time tracking, project operations and billing review for ERPNext"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "info@jitis.io"
app_license = "GPL-3.0-or-later"
required_apps = ["erpnext", "hrms"]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/working_time/css/working_time.css"
# app_include_js = "/assets/working_time/js/working_time.js"

# include js, css files in header of web template
# web_include_css = "/assets/working_time/css/working_time.css"
# web_include_js = "/assets/working_time/js/working_time.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "working_time/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Sales Order": "public/js/sales_order.js",
	"Customer Project Provisioning": "public/js/customer_project_provisioning.js",
	"Billing Review": "public/js/billing_review.js",
	"Platform Operations Settings": "public/js/platform_operations_settings.js",
	"Issue": "public/js/issue.js",
	"Project": "public/js/project.js",
	"Task": "public/js/task.js",
}

doctype_list_js = {
	"Billing Review": "public/js/billing_review_list.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Installation
# ------------

# before_install = "working_time.install.before_install"
after_install = "working_time.install.after_install"
after_migrate = "working_time.install.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "working_time.uninstall.before_uninstall"
# after_uninstall = "working_time.uninstall.after_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "working_time.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Working Time": "working_time.permissions.working_time_query_conditions",
}

has_permission = {
	"Working Time": "working_time.permissions.working_time_has_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# Scheduled Tasks
# ---------------

scheduler_events = {
	# 	"all": [
	# 		"working_time.tasks.all"
	# 	],
	"daily": [
		"working_time.reminders.create_daily_drafts",
		"working_time.reminders.send_stale_reminders",
		"working_time.reminders.send_month_end_reminders",
	],
	# 	"hourly": [
	# 		"working_time.tasks.hourly"
	# 	],
	# 	"weekly": [
	# 		"working_time.tasks.weekly"
	# 	]
	# 	"monthly": [
	# 		"working_time.tasks.monthly"
	# 	]
}

# Testing
# -------

# before_tests = "working_time.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "working_time.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "working_time.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
ignore_translatable_strings_from = ["frappe", "erpnext", "hrms"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"working_time.auth.validate"
# ]

working_time_custom_fields = {
	"Project": [
		{
			"fieldname": "billing_model",
			"label": "Billing Model",
			"fieldtype": "Select",
			"options": "Non-billable\nTime and Material\nFixed Price\nRecurring",
			"default": "Non-billable",
			"insert_after": "project_type",
		},
		{
			"fieldname": "billing_rate",
			"label": "Billing Rate per Hour",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "cost_center",
			"translatable": 0,
		},
		{
			"fieldname": "contract",
			"label": "Contract",
			"fieldtype": "Link",
			"options": "Contract",
			"insert_after": "sales_order",
		},
	],
	"Issue": [
		{
			"fieldname": "working_time_operational_state",
			"label": "Operational State",
			"fieldtype": "Select",
			"options": "Normal\nBlockiert\nWartet auf Kunde",
			"default": "Normal",
			"insert_after": "status",
		},
		{
			"fieldname": "working_time_planned_date",
			"label": "Planned Date",
			"fieldtype": "Date",
			"insert_after": "working_time_operational_state",
		},
	],
	"Task": [
		{
			"fieldname": "working_time_operational_state",
			"label": "Operational State",
			"fieldtype": "Select",
			"options": "Normal\nBlockiert\nWartet auf Kunde",
			"default": "Normal",
			"insert_after": "status",
		},
		{
			"fieldname": "working_time_issue_attachments_html",
			"label": "Issue Attachments",
			"fieldtype": "HTML",
			"insert_after": "issue",
			"depends_on": "eval:doc.issue",
		},
	],
	"Timesheet": [
		{
			"fieldname": "working_time",
			"label": "Working Time",
			"fieldtype": "Link",
			"options": "Working Time",
			"insert_after": "project",
			"translatable": 0,
			"read_only": 1,
		},
	],
	"Timesheet Detail": [
		{
			"fieldname": "issue",
			"label": "Issue",
			"fieldtype": "Link",
			"options": "Issue",
			"insert_after": "task",
			"read_only": 1,
		},
		{
			"fieldname": "customer_description",
			"label": "Customer Description",
			"fieldtype": "Small Text",
			"insert_after": "description",
			"read_only": 1,
		},
		{
			"fieldname": "internal_note",
			"label": "Internal Note",
			"fieldtype": "Small Text",
			"insert_after": "customer_description",
			"read_only": 1,
		},
	],
	"Attendance": [
		{
			"fieldname": "working_time",
			"label": "Working Time",
			"fieldtype": "Link",
			"options": "Working Time",
			"insert_after": "company",
			"translatable": 0,
			"read_only": 1,
		}
	],
	"Employee": [
		{
			"fieldname": "working_time_policy",
			"label": "Working Time Policy",
			"fieldtype": "Link",
			"options": "Working Time Policy",
			"insert_after": "holiday_list",
		}
	],
	"Sales Order": [
		{
			"fieldname": "customer_project_provisioning",
			"label": "Customer Project Provisioning",
			"fieldtype": "Link",
			"options": "Customer Project Provisioning",
			"insert_after": "customer_name",
			"read_only": 1,
			"translatable": 0,
		},
	],
}
