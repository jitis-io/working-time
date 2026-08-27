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


class TimeBookingClientScriptTest(TestCase):
	def test_optional_daily_close_uses_the_booked_working_time_record(self):
		script = (APP_ROOT / "public" / "js" / "time_booking.js").read_text(encoding="utf-8")

		self.assertIn('fieldname: "open_daily_close"', script)
		self.assertIn('label: __("Open daily close after booking")', script)
		self.assertIn("if (values.open_daily_close && !(await open_booked_daily_close(result)))", script)
		self.assertIn('typeof result?.working_time === "string"', script)
		self.assertIn('await frappe.set_route("Form", "Working Time", working_time);', script)
		self.assertNotIn('frappe.set_route("Form", "Working Time", requested_date)', script)

	def test_existing_on_booked_callback_runs_before_optional_navigation(self):
		script = (APP_ROOT / "public" / "js" / "time_booking.js").read_text(encoding="utf-8")
		callback = 'if (typeof options.on_booked === "function")'
		navigation = "if (values.open_daily_close && !(await open_booked_daily_close(result)))"

		self.assertLess(script.index(callback), script.index(navigation))
		self.assertNotIn("if (await open_booked_daily_close(result)) return;", script)

	def test_navigation_failure_does_not_reenter_the_booking_error_path(self):
		script = (APP_ROOT / "public" / "js" / "time_booking.js").read_text(encoding="utf-8")
		helper_start = script.index("async function open_booked_daily_close(result)")
		helper_end = script.index("async function build_dialog(options)", helper_start)
		helper = script[helper_start:helper_end]

		self.assertIn("try {", helper)
		self.assertIn("} catch {", helper)
		self.assertIn("return false;", helper)
		self.assertIn('await frappe.set_route("Form", "Working Time", working_time);', helper)

	def test_optional_daily_close_messages_are_translatable(self):
		german = (APP_ROOT / "locale" / "de.po").read_text(encoding="utf-8")
		english = (APP_ROOT / "locale" / "en.po").read_text(encoding="utf-8")

		for catalog in (german, english):
			self.assertIn('msgid "Open daily close after booking"', catalog)
			self.assertIn('msgid "The daily close for the selected date will open."', catalog)
			self.assertIn('msgid "Time was booked, but the daily close could not be opened."', catalog)
