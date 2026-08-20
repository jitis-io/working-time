import json
import sys
import types
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch


def _bootstrap_frappe_stub() -> None:
	if "frappe" in sys.modules:
		return

	def throw(message, exc=None, *args, **kwargs):
		del args, kwargs
		raise (exc or RuntimeError)(message)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda message: message
	frappe.throw = throw
	frappe.ValidationError = type("ValidationError", (Exception,), {})
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.whitelist = lambda *args, **kwargs: lambda fn: fn
	frappe.db = types.SimpleNamespace(
		get_value=lambda *args, **kwargs: None,
		sql=lambda *args, **kwargs: [],
	)
	frappe.get_all = lambda *args, **kwargs: []
	frappe.get_doc = lambda *args, **kwargs: None
	frappe.get_list = lambda *args, **kwargs: []
	frappe.get_roles = lambda *args, **kwargs: []
	frappe.has_permission = lambda *args, **kwargs: True
	frappe.session = types.SimpleNamespace(user="test@example.com")
	frappe_utils = types.ModuleType("frappe.utils")
	frappe_utils.nowdate = lambda: "2026-08-20"
	frappe.utils = frappe_utils
	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = frappe_utils


_bootstrap_frappe_stub()

frappe_utils = sys.modules.setdefault("frappe.utils", types.ModuleType("frappe.utils"))
frappe_utils.nowdate = getattr(frappe_utils, "nowdate", lambda: "2026-08-20")

import frappe

from working_time.project_overview import (
	_aggregate_invoice_rows,
	_aggregate_time_rows,
	_month_period,
	_permitted_time_rows,
	_purchase_invoice_item_rows,
	_time_entry_rows,
	get_project_month,
)


class FakeDocument(types.SimpleNamespace):
	def get(self, key, default=None):
		return getattr(self, key, default)


class TestProjectOverview(unittest.TestCase):
	def test_month_period_is_exactly_one_calendar_month(self):
		period = _month_period("2024-02")

		self.assertEqual(period["month"], "2024-02")
		self.assertEqual(period["start"], date(2024, 2, 1))
		self.assertEqual(period["end"], date(2024, 2, 29))
		self.assertEqual(period["next_start"], date(2024, 3, 1))

	def test_month_period_defaults_to_the_injected_current_month(self):
		period = _month_period(today=date(2026, 12, 31))

		self.assertEqual(period["month"], "2026-12")
		self.assertEqual(period["start"], date(2026, 12, 1))
		self.assertEqual(period["end"], date(2026, 12, 31))
		self.assertEqual(period["next_start"], date(2027, 1, 1))

	def test_month_period_rejects_ranges_and_non_padded_values(self):
		for invalid in ("", "2026-8", "2026-08-01", "2026-08,2026-09", "2026-13"):
			with self.subTest(invalid=invalid), self.assertRaises(frappe.ValidationError):
				_month_period(invalid)

	def test_time_aggregation_only_marks_uninvoiced_unclaimed_billable_rows_unbilled(self):
		rows = [
			{
				"name": "TD-1",
				"timesheet": "TS-1",
				"from_time": datetime(2026, 8, 20, 9),
				"employee": "EMP-1",
				"employee_name": "Ada",
				"activity_type": "Default",
				"issue": "ISS-1",
				"task": None,
				"description": "Support",
				"hours": Decimal("1.5"),
				"billable_hours": Decimal("1.25"),
				"cost": Decimal("75"),
				"billable_amount": Decimal("150"),
				"sales_invoice": None,
			},
			{
				"name": "TD-2",
				"timesheet": "TS-1",
				"from_time": datetime(2026, 8, 20, 11),
				"hours": Decimal("0.5"),
				"billable_hours": Decimal("0.5"),
				"cost": Decimal("25"),
				"billable_amount": Decimal("60"),
				"sales_invoice": None,
			},
			{
				"name": "TD-3",
				"timesheet": "TS-2",
				"from_time": datetime(2026, 8, 19, 9),
				"hours": Decimal("2"),
				"billable_hours": Decimal("2"),
				"cost": Decimal("100"),
				"billable_amount": Decimal("240"),
				"sales_invoice": "SINV-1",
			},
			{
				"name": "TD-4",
				"timesheet": "TS-3",
				"from_time": datetime(2026, 8, 18, 9),
				"hours": Decimal("1"),
				"billable_hours": Decimal("0"),
				"cost": Decimal("50"),
				"billable_amount": Decimal("0"),
				"sales_invoice": None,
			},
		]

		summary, entries = _aggregate_time_rows(rows, {"TD-2": "Draft Created"})

		self.assertEqual(
			summary,
			{
				"hours": 5.0,
				"billable_hours": 3.75,
				"unbilled_hours": 1.25,
				"time_cost": 250.0,
				"billable_amount": 450.0,
				"unbilled_amount": 150.0,
			},
		)
		self.assertEqual(entries[0]["date"], "2026-08-20")
		self.assertEqual(entries[0]["unbilled_amount"], 150.0)
		self.assertEqual(entries[1]["unbilled_amount"], 0.0)
		self.assertEqual(entries[2]["unbilled_amount"], 0.0)
		json.dumps({"summary": summary, "entries": entries})

	def test_invoice_item_aggregation_preserves_credit_note_signs(self):
		rows = [
			{
				"name": "PINV-1",
				"posting_date": date(2026, 8, 20),
				"supplier": "SUP-1",
				"supplier_name": "Supplier",
				"status": "Unpaid",
				"docstatus": 1,
				"is_return": 0,
				"amount": Decimal("100"),
			},
			{
				"name": "PINV-1",
				"posting_date": date(2026, 8, 20),
				"supplier": "SUP-1",
				"supplier_name": "Supplier",
				"status": "Unpaid",
				"docstatus": 1,
				"is_return": 0,
				"amount": Decimal("-10"),
			},
			{
				"name": "PINV-RET-1",
				"posting_date": date(2026, 8, 19),
				"supplier": "SUP-1",
				"supplier_name": "Supplier",
				"status": "Return",
				"docstatus": 1,
				"is_return": 1,
				"amount": Decimal("-25"),
			},
		]

		invoices = _aggregate_invoice_rows(rows, party_field="supplier", party_name_field="supplier_name")

		self.assertEqual([row["name"] for row in invoices], ["PINV-1", "PINV-RET-1"])
		self.assertEqual(invoices[0]["amount"], 90.0)
		self.assertEqual(invoices[1]["amount"], -25.0)
		self.assertTrue(invoices[1]["is_return"])

	def test_queries_use_parameters_and_required_project_fallback(self):
		period = _month_period("2026-08")
		project = "PROJ-' OR 1=1 --"
		with patch.object(frappe.db, "sql", return_value=[]) as sql:
			_purchase_invoice_item_rows(project, "JITIS", period)

		query, values = sql.call_args.args
		self.assertNotIn(project, query)
		self.assertIn("coalesce(nullif(pii.project, ''), pi.project) = %(project)s", query)
		self.assertEqual(values["project"], project)
		self.assertEqual(values["start"], date(2026, 8, 1))
		self.assertEqual(values["next_start"], date(2026, 9, 1))
		self.assertTrue(sql.call_args.kwargs["as_dict"])

	def test_time_query_uses_submitted_parent_and_exclusive_month_end(self):
		period = _month_period("2026-08")
		with patch.object(frappe.db, "sql", return_value=[]) as sql:
			_time_entry_rows("PROJ-1", period)

		query, values = sql.call_args.args
		self.assertIn("inner join `tabTimesheet`", query)
		self.assertIn("ts.docstatus = 1", query)
		self.assertIn("td.from_time < %(next_start)s", query)
		self.assertEqual(values["project"], "PROJ-1")

	def test_project_read_permission_is_checked_before_data_queries(self):
		project_doc = FakeDocument(name="PROJ-1")
		with (
			patch("working_time.project_overview.frappe.get_doc", return_value=project_doc),
			patch("working_time.project_overview.frappe.has_permission", return_value=False),
			patch("working_time.project_overview._time_entry_rows") as time_rows,
			self.assertRaises(frappe.PermissionError),
		):
			get_project_month("PROJ-1", "2026-08")

		time_rows.assert_not_called()

	def test_can_book_time_requires_an_open_active_project(self):
		cases = (
			("Open", "Yes", True),
			("Completed", "Yes", False),
			("Cancelled", "Yes", False),
			("Open", "No", False),
		)

		def has_permission(doctype, permission_type, **kwargs):
			del permission_type, kwargs
			return doctype in {"Project", "Working Time"}

		for status, is_active, expected in cases:
			with self.subTest(status=status, is_active=is_active):
				project_doc = FakeDocument(
					name="PROJ-1",
					project_name="Customer project",
					customer="CUST-1",
					company=None,
					status=status,
					is_active=is_active,
					time_billable=1,
					billing_rate=120,
				)
				with (
					patch("working_time.project_overview.frappe.get_doc", return_value=project_doc),
					patch(
						"working_time.project_overview.frappe.has_permission",
						side_effect=has_permission,
					),
					patch("working_time.project_overview.get_user_employee", return_value="EMP-1"),
					patch("working_time.project_overview.is_system_manager", return_value=False),
				):
					result = get_project_month("PROJ-1", "2026-08")

				self.assertEqual(result["capabilities"]["can_book_time"], expected)

	def test_timesheet_rows_are_filtered_once_per_parent_document(self):
		rows = [
			{"name": "TD-1", "timesheet": "TS-VISIBLE"},
			{"name": "TD-2", "timesheet": "TS-VISIBLE"},
			{"name": "TD-3", "timesheet": "TS-HIDDEN"},
		]

		with patch(
			"working_time.project_overview.frappe.has_permission",
			side_effect=lambda doctype, permission_type, doc=None: doc == "TS-VISIBLE",
		) as has_permission:
			visible = _permitted_time_rows(rows)

		self.assertEqual([row["name"] for row in visible], ["TD-1", "TD-2"])
		self.assertEqual(has_permission.call_count, 2)

	def test_financial_invoice_queries_fail_closed_without_doctype_read_permission(self):
		project_doc = FakeDocument(
			name="PROJ-1",
			project_name="Customer project",
			customer="CUST-1",
			company="JITIS",
			time_billable=1,
			billing_model="Time and Material",
			billing_rate=120,
		)

		def has_permission(doctype, permission_type, **kwargs):
			del permission_type, kwargs
			return doctype == "Project"

		with (
			patch("working_time.project_overview.frappe.get_doc", return_value=project_doc),
			patch("working_time.project_overview.frappe.has_permission", side_effect=has_permission),
			patch("working_time.project_overview.frappe.db.get_value", return_value="EUR"),
			patch("working_time.project_overview.get_user_employee", return_value=None),
			patch("working_time.project_overview.is_system_manager", return_value=False),
			patch("working_time.project_overview._claimed_billing_sources", return_value={}),
			patch(
				"working_time.project_overview._time_entry_rows",
				return_value=[
					{
						"name": "TD-1",
						"hours": 1,
						"billable_hours": 1,
						"cost": 50,
						"billable_amount": 120,
					}
				],
			) as time_entries_query,
			patch("working_time.project_overview._purchase_invoice_item_rows") as purchases,
			patch("working_time.project_overview._sales_invoice_item_rows") as sales,
		):
			result = get_project_month("PROJ-1", "2026-08")

		purchases.assert_not_called()
		sales.assert_not_called()
		time_entries_query.assert_not_called()
		self.assertEqual(result["summary"]["hours"], 0.0)
		self.assertEqual(result["summary"]["time_cost"], 0.0)
		self.assertFalse(result["capabilities"]["can_view_purchases"])
		self.assertFalse(result["capabilities"]["can_view_sales"])
		self.assertEqual(result["summary"]["purchase_cost"], 0.0)
		self.assertEqual(result["summary"]["sales_invoiced"], 0.0)
		self.assertEqual(result["summary"]["sales_draft"], 0.0)
		self.assertEqual(result["rows"]["purchase_invoices"], [])
		self.assertEqual(result["rows"]["sales_invoices"], [])

	def test_endpoint_totals_all_visible_rows_but_returns_at_most_eight(self):
		project_doc = FakeDocument(
			name="PROJ-1",
			project_name="Customer project",
			customer="CUST-1",
			company="JITIS",
			time_billable=1,
			billing_model="Time and Material",
			billing_rate=120,
		)
		time_rows = [
			{
				"name": f"TD-{index}",
				"timesheet": f"TS-{index}",
				"from_time": datetime(2026, 8, 20, 9),
				"hours": 1,
				"billable_hours": 1,
				"cost": 10,
				"billable_amount": 20,
			}
			for index in range(10)
		]
		purchases = [
			{
				"name": f"PINV-{index}",
				"posting_date": date(2026, 8, 20),
				"supplier": "SUP-1",
				"supplier_name": "Supplier",
				"status": "Draft" if index == 8 else "Unpaid",
				"docstatus": 0 if index == 8 else 1,
				"is_return": 0,
				"amount": 25,
			}
			for index in range(9)
		]
		purchases.append(
			{
				"name": "PINV-RETURN",
				"posting_date": date(2026, 8, 19),
				"supplier": "SUP-1",
				"supplier_name": "Supplier",
				"status": "Return",
				"docstatus": 1,
				"is_return": 1,
				"amount": -10,
			}
		)
		sales = [
			{
				"name": "SINV-1",
				"posting_date": date(2026, 8, 20),
				"customer": "CUST-1",
				"customer_name": "Customer",
				"status": "Unpaid",
				"docstatus": 1,
				"is_return": 0,
				"amount": 500,
			},
			{
				"name": "SINV-DRAFT",
				"posting_date": date(2026, 8, 20),
				"customer": "CUST-1",
				"customer_name": "Customer",
				"status": "Draft",
				"docstatus": 0,
				"is_return": 0,
				"amount": 100,
			},
		]

		def get_list(doctype, **kwargs):
			del kwargs
			return [{"name": "one"}, {"name": "two"}] if doctype == "Issue" else []

		with (
			patch("working_time.project_overview.frappe.get_doc", return_value=project_doc),
			patch("working_time.project_overview.frappe.has_permission", return_value=True),
			patch("working_time.project_overview.frappe.db.get_value", return_value="EUR"),
			patch("working_time.project_overview.frappe.get_list", side_effect=get_list),
			patch("working_time.project_overview.get_user_employee", return_value="EMP-1"),
			patch("working_time.project_overview.is_system_manager", return_value=True),
			patch("working_time.project_overview._claimed_billing_sources", return_value={}),
			patch("working_time.project_overview._time_entry_rows", return_value=time_rows),
			patch("working_time.project_overview._purchase_invoice_item_rows", return_value=purchases),
			patch("working_time.project_overview._sales_invoice_item_rows", return_value=sales),
		):
			result = get_project_month("PROJ-1", "2026-08")

		self.assertEqual(result["period"]["start"], "2026-08-01")
		self.assertEqual(result["period"]["end"], "2026-08-31")
		self.assertEqual(result["project"]["currency"], "EUR")
		self.assertTrue(result["project"]["time_billable"])
		self.assertEqual(result["summary"]["hours"], 10.0)
		self.assertEqual(result["summary"]["purchase_cost"], 190.0)
		self.assertEqual(result["summary"]["sales_invoiced"], 500.0)
		self.assertEqual(result["summary"]["sales_draft"], 100.0)
		self.assertEqual(result["summary"]["margin"], 210.0)
		self.assertEqual(result["counts"]["open_issues"], 2)
		self.assertEqual(result["counts"]["open_tasks"], 0)
		self.assertEqual(result["counts"]["purchase_invoices"], 10)
		self.assertEqual(result["counts"]["sales_invoices"], 2)
		self.assertEqual(len(result["rows"]["time_entries"]), 8)
		self.assertEqual(len(result["rows"]["purchase_invoices"]), 8)
		self.assertEqual(len(result["rows"]["sales_invoices"]), 2)
		json.dumps(result)


if __name__ == "__main__":
	unittest.main()
