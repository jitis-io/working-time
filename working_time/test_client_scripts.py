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
