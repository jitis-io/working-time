import shutil
import subprocess
from pathlib import Path
from unittest import TestCase

APP_ROOT = Path(__file__).resolve().parent


class InvoiceProjectClientScriptTest(TestCase):
	def test_invoice_item_row_render_does_not_rebuild_the_open_grid(self):
		script = (APP_ROOT / "public" / "js" / "invoice_project.js").read_text(encoding="utf-8")

		self.assertIn('for (const doctype of ["Purchase Invoice", "Sales Invoice"])', script)
		self.assertIn("apply_route_project(frm);", script)
		self.assertNotIn("items_on_form_rendered", script)
		self.assertNotIn("set_column_disp_in_list_view", script)
		self.assertNotIn("update_docfield_property", script)


class BillingReviewListClientScriptTest(TestCase):
	def test_monthly_review_uses_the_preview_api_for_all_projects(self):
		hooks = (APP_ROOT / "hooks.py").read_text(encoding="utf-8")
		script = (APP_ROOT / "public" / "js" / "billing_review_list.js").read_text(encoding="utf-8")

		self.assertIn('"Billing Review": "public/js/billing_review_list.js"', hooks)
		self.assertIn('__("Prepare month")', script)
		self.assertIn('frappe.user.has_role("System Manager")', script)
		self.assertIn("frappe.datetime.month_start(today)", script)
		self.assertIn("frappe.datetime.month_end(today)", script)
		self.assertIn("working_time.platform_operations.create_billing_review", script)
		self.assertNotIn("create_billing_invoice_drafts", script)
		self.assertNotIn("project:", script.lower())
		for filename in ("de.po", "en.po", "main.pot"):
			catalog = (APP_ROOT / "locale" / filename).read_text(encoding="utf-8")
			self.assertIn('msgid "Prepare month"', catalog)
		german = (APP_ROOT / "locale" / "de.po").read_text(encoding="utf-8")
		self.assertIn('msgstr "Monat vorbereiten"', german)


class TimeBookingClientScriptTest(TestCase):
	def test_booking_and_navigation_runtime_semantics(self):
		node = shutil.which("node")
		self.assertIsNotNone(node, "Node.js is required for the client runtime semantics test")
		harness = APP_ROOT.parent / "ci" / "test-time-booking-client-runtime.mjs"
		completed = subprocess.run(
			[node, str(harness)],
			cwd=APP_ROOT.parent,
			capture_output=True,
			text=True,
			timeout=30,
			check=False,
		)
		self.assertEqual(
			completed.returncode,
			0,
			f"Node runtime semantics test failed:\n{completed.stdout}\n{completed.stderr}",
		)

	def test_optional_daily_close_uses_the_booked_working_time_record(self):
		script = (APP_ROOT / "public" / "js" / "time_booking.js").read_text(encoding="utf-8")

		self.assertIn('fieldname: "open_daily_close"', script)
		self.assertIn('label: __("Open daily close after booking")', script)
		self.assertIn("!(await start_booked_daily_close_navigation(result))", script)
		self.assertIn('typeof result?.working_time === "string"', script)
		self.assertIn('await frappe.set_route("Form", "Working Time", working_time);', script)
		self.assertNotIn('frappe.set_route("Form", "Working Time", requested_date)', script)

	def test_existing_on_booked_callback_runs_before_optional_navigation(self):
		script = (APP_ROOT / "public" / "js" / "time_booking.js").read_text(encoding="utf-8")
		callback = 'if (typeof options.on_booked === "function")'
		navigation = "!(await start_booked_daily_close_navigation(result))"

		self.assertLess(script.index(callback), script.index(navigation))
		self.assertNotIn("if (await start_booked_daily_close_navigation(result)) return;", script)

	def test_navigation_start_failure_does_not_reenter_the_booking_error_path(self):
		script = (APP_ROOT / "public" / "js" / "time_booking.js").read_text(encoding="utf-8")
		helper_start = script.index("async function start_booked_daily_close_navigation(result)")
		helper_end = script.index("async function build_dialog(options)", helper_start)
		helper = script[helper_start:helper_end]

		self.assertIn("try {", helper)
		self.assertIn("} catch {", helper)
		self.assertIn("return false;", helper)
		self.assertIn('await frappe.set_route("Form", "Working Time", working_time);', helper)

	def test_optional_daily_close_messages_are_translatable(self):
		catalogs = [
			(APP_ROOT / "locale" / filename).read_text(encoding="utf-8")
			for filename in ("de.po", "en.po", "main.pot")
		]

		for catalog in catalogs:
			self.assertIn('msgid "Open daily close after booking"', catalog)
			self.assertIn('msgid "The daily close for the selected date will open."', catalog)
			self.assertIn(
				'msgid "Time was booked, but navigation to the daily close could not be started."',
				catalog,
			)


class ProjectDailyCloseClientScriptTest(TestCase):
	def test_daily_close_runtime_unlocks_after_native_conflict(self):
		node = shutil.which("node")
		self.assertIsNotNone(node, "Node.js is required for the Daily close runtime test")
		harness = APP_ROOT.parent / "ci" / "test-project-daily-close-runtime.mjs"
		completed = subprocess.run(
			[node, str(harness)],
			cwd=APP_ROOT.parent,
			capture_output=True,
			text=True,
			timeout=30,
			check=False,
		)
		self.assertEqual(
			completed.returncode,
			0,
			f"Daily close runtime test failed:\n{completed.stdout}\n{completed.stderr}",
		)

	def test_daily_close_conflict_message_is_translatable(self):
		message = "A concurrent request interrupted opening the daily close. Please try again."
		for filename in ("de.po", "en.po", "main.pot"):
			catalog = (APP_ROOT / "locale" / filename).read_text(encoding="utf-8")
			self.assertIn(f'msgid "{message}"', catalog)
