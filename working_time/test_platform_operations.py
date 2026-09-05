import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import call, patch


def _bootstrap_frappe_stub() -> None:
	if "frappe" in sys.modules:
		return

	def throw(message, exc=None, *args, **kwargs):
		del args, kwargs
		raise (exc or RuntimeError)(message)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda message: message
	frappe.throw = throw
	frappe.ValidationError = RuntimeError
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.only_for = lambda *args, **kwargs: None
	frappe.whitelist = lambda *args, **kwargs: lambda fn: fn
	frappe.db = types.SimpleNamespace(
		get_value=lambda *args, **kwargs: None,
		exists=lambda *args, **kwargs: False,
		set_value=lambda *args, **kwargs: None,
		escape=lambda value: repr(value),
		sql=lambda *args, **kwargs: [],
	)
	frappe.get_roles = lambda *args, **kwargs: []
	frappe.get_all = lambda *args, **kwargs: []
	frappe.get_doc = lambda *args, **kwargs: None
	frappe.get_list = lambda *args, **kwargs: []
	frappe.get_single = lambda *args, **kwargs: None
	frappe.get_precision = lambda *args, **kwargs: 6
	frappe.has_permission = lambda *args, **kwargs: True
	frappe.session = types.SimpleNamespace(user="test@example.com")
	frappe_utils = types.ModuleType("frappe.utils")
	frappe_utils.nowdate = lambda: "2026-08-20"
	frappe_utils.flt = lambda value, precision: round(float(value), precision)
	frappe.utils = frappe_utils
	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = frappe_utils


_bootstrap_frappe_stub()

import frappe

FrappeValidationError = getattr(frappe, "ValidationError", RuntimeError)

from working_time.platform_operations import (
	_aggregate_billing_sources,
	_billing_source,
	_billing_status,
	_invoice_description,
	_invoice_timesheet_rows,
	_lock_billing_sources,
	_review_source_items,
	_round_billable_hours,
	_sales_order_time_billing_row,
	_synchronize_billing_review_status,
	create_billing_invoice_drafts,
	create_billing_review,
	create_project_time_invoice_draft,
	finalize_billing_review,
	synchronize_billing_reviews_for_invoice,
	validate_billing_review_invoice_sources,
)


class FakeDocument(types.SimpleNamespace):
	def get(self, key, default=None):
		return getattr(self, key, default)

	def insert(self, **kwargs):
		self.inserted = True
		return self

	def save(self, **kwargs):
		self.saved = True
		return self

	def append(self, fieldname, values):
		row = FakeDocument(**values)
		rows = getattr(self, fieldname, None)
		if rows is None:
			rows = []
			setattr(self, fieldname, rows)
		rows.append(row)
		return row


def _locked_source(name="ROW-0001", *, project="PROJ-0001", billing_hours=0.2, sales_invoice=None, rate=120):
	return FakeDocument(
		name=name,
		parent="TS-0001",
		parenttype="Timesheet",
		docstatus=1,
		project=project,
		project_name=project,
		is_billable=1,
		billing_hours=billing_hours,
		base_billing_rate=rate,
		sales_invoice=sales_invoice,
		from_time="2026-08-01 09:00:00",
		to_time="2026-08-01 09:12:00",
		activity_type="Support",
		customer_description="Customer-visible work",
		description="Internal work",
	)


class TestPlatformOperations(unittest.TestCase):
	def test_time_billing_row_requires_hour_uom_and_unit_conversion(self):
		for uom, conversion_factor in (("Day", 1), ("Hour", 60)):
			with self.subTest(uom=uom, conversion_factor=conversion_factor):
				sales_order = FakeDocument(
					name="SO-0001",
					items=[
						FakeDocument(
							name="SOI-0001",
							item_code="TIME",
							rate=119,
							uom=uom,
							conversion_factor=conversion_factor,
						)
					],
				)
				with self.assertRaises(FrappeValidationError):
					_sales_order_time_billing_row(sales_order, "TIME")

	def test_no_automatic_external_reconciliation(self):
		from working_time.hooks import scheduler_events

		self.assertNotIn("cron", scheduler_events)

	def test_billable_rounding_is_upward_to_quarter_hour(self):
		self.assertEqual(_round_billable_hours(0), 0)
		self.assertEqual(_round_billable_hours("0.10"), 0.25)
		self.assertEqual(_round_billable_hours("0.25"), 0.25)
		self.assertEqual(_round_billable_hours("0.26"), 0.5)

	def test_billing_uses_submitted_company_currency_rate_after_project_tariff_change(self):
		detail = FakeDocument(
			name="ROW-1",
			project="PROJ-1",
			base_billing_rate=119,
			billing_rate=100,
			is_billable=1,
			billing_hours=1,
			hours=1,
		)
		project = FakeDocument(name="PROJ-1", customer="CUST-1", time_billable=1, billing_rate=139)
		with (
			patch("working_time.platform_operations.frappe.get_doc", return_value=project),
			patch("working_time.platform_operations.frappe.db.get_value", return_value="PROJ-1"),
		):
			status, context = _billing_status(detail, {})
		self.assertEqual(status, "Eligible")
		source = _billing_source(detail, FakeDocument(name="TS-1", start_date="2026-09-05"), status, context)
		self.assertEqual(source["rate"], 119)

	def test_missing_historical_rate_never_falls_back_to_current_project_tariff(self):
		project = FakeDocument(name="PROJ-1", customer="CUST-1", time_billable=1, billing_rate=139)
		for rate in (None, 0, -1):
			detail = FakeDocument(name="ROW-1", project="PROJ-1", base_billing_rate=rate)
			with (
				self.subTest(rate=rate),
				patch("working_time.platform_operations.frappe.get_doc", return_value=project),
			):
				status, _ = _billing_status(detail, {})
			self.assertEqual(status, "Missing Rate")

	def test_different_submitted_rates_never_share_a_rounded_billing_group(self):
		base = {
			"customer": "CUST-1",
			"project": "PROJ-1",
			"task": None,
			"work_date": "2026-09-05",
			"timesheet": "TS-1",
			"actual_hours": 0.1,
			"raw_billable_hours": 0.1,
		}
		groups = _aggregate_billing_sources(
			[
				{**base, "timesheet_detail": "ROW-1", "rate": 119},
				{**base, "timesheet_detail": "ROW-2", "rate": 139},
			]
		)
		self.assertEqual(len(groups), 2)
		self.assertEqual(
			sorted((g["rate"], g["hours"], g["amount"]) for g in groups),
			[(119, 0.25, 29.75), (139, 0.25, 34.75)],
		)

	def test_source_rate_change_and_missing_snapshot_block_invoice_draft(self):
		item = FakeDocument(
			project="PROJ-0001", rate=119, timesheet_detail="ROW-0001", source_count=1, raw_billable_hours=0.2
		)
		for changed_rate in (0, 120):
			with (
				self.subTest(rate=changed_rate),
				patch(
					"working_time.platform_operations.frappe.db.sql",
					return_value=[_locked_source(rate=changed_rate)],
				),
				self.assertRaisesRegex(FrappeValidationError, "changed after the preview"),
			):
				_lock_billing_sources(_review_source_items([item]))

	def test_billing_sources_are_aggregated_before_rounding(self):
		base = {
			"customer": "CUST-0001",
			"project": "PROJ-0001",
			"task": "TASK-0001",
			"work_date": "2026-08-01",
			"sales_order": "SO-0001",
			"rate": 120,
			"status": "Eligible",
		}
		groups = _aggregate_billing_sources(
			[
				{
					**base,
					"timesheet": "TS-0001",
					"timesheet_detail": "ROW-0001",
					"actual_hours": "0.10",
					"raw_billable_hours": "0.10",
					"issue": "ISS-2026-00001",
					"customer_description": "First intervention",
				},
				{
					**base,
					"timesheet": "TS-0002",
					"timesheet_detail": "ROW-0002",
					"actual_hours": "0.10",
					"raw_billable_hours": "0.10",
					"issue": "ISS-2026-00002",
					"customer_description": "Second intervention",
				},
				{
					**base,
					"task": "TASK-0002",
					"timesheet": "TS-0003",
					"timesheet_detail": "ROW-0003",
					"actual_hours": "0.10",
					"raw_billable_hours": "0.10",
				},
			]
		)

		self.assertEqual(len(groups), 2)
		first = next(group for group in groups if group["task"] == "TASK-0001")
		self.assertEqual(first["actual_hours"], 0.2)
		self.assertEqual(first["raw_billable_hours"], 0.2)
		self.assertEqual(first["hours"], 0.25)
		self.assertEqual(first["amount"], 30)
		self.assertEqual(len(first["sources"]), 2)
		self.assertIsNone(first["issue"])
		self.assertEqual(first["ticket_references"], "ISS-2026-00001, ISS-2026-00002")
		self.assertEqual(first["customer_description"], "First intervention; Second intervention")

	def test_internal_timesheet_description_never_reaches_invoice_text(self):
		secret = "INTERNAL: credentials and technician-only diagnostic notes"
		detail = FakeDocument(
			name="ROW-0001",
			project="PROJ-INTERNAL-ID",
			task="TASK-INTERNAL-ID",
			issue=None,
			customer_description="  ",
			description=secret,
			from_time="2026-08-01 09:00:00",
			hours=0.2,
			billing_hours=0.2,
			is_billable=1,
		)
		project = FakeDocument(name="PROJ-INTERNAL-ID", customer="CUST-0001", billing_rate=120)
		source = _billing_source(
			detail,
			FakeDocument(name="TS-0001", start_date="2026-08-01"),
			"Eligible",
			{"project": project, "sales_order": None},
		)
		self.assertEqual(source["customer_description"], "")

		item = FakeDocument(
			project="PROJ-INTERNAL-ID",
			task="TASK-INTERNAL-ID",
			work_date="2026-08-01",
			ticket_references="",
			customer_description="",
			rate=120,
			timesheet_detail="ROW-0001",
			source_details_json="",
		)
		locked_source = _locked_source()
		locked_source.customer_description = ""
		locked_source.description = secret
		invoice_text = _invoice_description(item)
		timesheet_text = _invoice_timesheet_rows([item], {"ROW-0001": locked_source})[0]["description"]
		self.assertEqual(invoice_text, "IT-Leistung am 2026-08-01")
		self.assertEqual(timesheet_text, invoice_text)
		for forbidden in (secret, "PROJ-INTERNAL-ID", "TASK-INTERNAL-ID"):
			self.assertNotIn(forbidden, invoice_text)
			self.assertNotIn(forbidden, timesheet_text)

	def test_invoice_timesheet_snapshot_keeps_ticket_and_customer_description_together(self):
		item = FakeDocument(
			project="PROJ-0001",
			work_date="2026-08-01",
			ticket_references="ISS-2026-00001",
			customer_description="WLAN-Störung behoben",
			rate=120,
			timesheet_detail="ROW-0001",
			source_details_json="",
		)
		locked_source = _locked_source()
		locked_source.customer_description = "WLAN-Störung behoben"
		locked_source.description = "Interne Diagnose und Zugangsdaten"

		row = _invoice_timesheet_rows([item], {"ROW-0001": locked_source})[0]

		self.assertEqual(
			row["description"],
			"IT-Leistung am 2026-08-01 - Support-Ticket ISS-2026-00001 - WLAN-Störung behoben",
		)
		self.assertNotIn("Interne Diagnose", row["description"])
		self.assertIsNone(row["activity_type"])
		self.assertEqual(row["working_time_customer_snapshot"], 1)

	def test_claimed_billing_source_wins_over_changed_project_configuration(self):
		detail = FakeDocument(name="ROW-0001", project="PROJ-0001")
		with patch("working_time.platform_operations.frappe.get_doc") as get_doc:
			status, context = _billing_status(detail, {"ROW-0001": "Draft Created"})

		self.assertEqual(status, "Already Drafted")
		self.assertEqual(context, {})
		get_doc.assert_not_called()

	def test_native_sales_invoice_reference_fails_closed_before_project_lookup(self):
		for docstatus, expected_status in (
			(0, "Already Drafted"),
			(1, "Already Invoiced"),
			(2, "Already Invoiced"),
			(None, "Already Invoiced"),
		):
			with self.subTest(docstatus=docstatus):
				detail = FakeDocument(
					name="ROW-0001",
					project="PROJ-0001",
					sales_invoice="SINV-NATIVE",
				)
				with (
					patch(
						"working_time.platform_operations.frappe.db.get_value",
						return_value=docstatus,
					) as get_value,
					patch("working_time.platform_operations.frappe.get_doc") as get_doc,
				):
					status, context = _billing_status(detail, {})

				self.assertEqual(status, expected_status)
				self.assertEqual(context, {})
				get_value.assert_called_once_with("Sales Invoice", "SINV-NATIVE", "docstatus")
				get_doc.assert_not_called()

	def test_source_lock_revalidates_exact_rows_in_deterministic_order(self):
		item = FakeDocument(
			project="PROJ-0001",
			rate=120,
			source_count=2,
			raw_billable_hours=0.4,
			source_details_json=('[{"timesheet_detail":"ROW-0002"},{"timesheet_detail":"ROW-0001"}]'),
			timesheet_detail=None,
		)
		source_items = _review_source_items([item])
		rows = [
			_locked_source("ROW-0001", billing_hours=0.2),
			_locked_source("ROW-0002", billing_hours=0.2),
		]
		with patch("working_time.platform_operations.frappe.db.sql", return_value=rows) as sql:
			locked = _lock_billing_sources(source_items)

		self.assertEqual(sorted(locked), ["ROW-0001", "ROW-0002"])
		query, params = sql.call_args.args
		self.assertIn("order by name", query.lower())
		self.assertIn("for update", query.lower())
		self.assertEqual(params, ("ROW-0001", "ROW-0002"))
		self.assertEqual(sql.call_args.kwargs, {"as_dict": True})

	def test_source_lock_compares_persisted_precision_and_still_rejects_drift(self):
		for precision, preview, changed in ((6, 0.233333, 0.233334), (4, 0.2333, 0.2334)):
			item = FakeDocument(
				project="PROJ-0001",
				rate=120,
				source_count=2,
				raw_billable_hours=preview,
				source_details_json='[{"timesheet_detail":"ROW-0001"},{"timesheet_detail":"ROW-0002"}]',
				timesheet_detail=None,
			)
			rows = [
				_locked_source("ROW-0001", billing_hours=0.116666667),
				_locked_source("ROW-0002", billing_hours=0.116666667),
			]
			with (
				self.subTest(precision=precision),
				patch("working_time.platform_operations.frappe.db.sql", return_value=rows),
				patch("working_time.platform_operations.frappe.get_precision", return_value=precision),
			):
				self.assertEqual(len(_lock_billing_sources(_review_source_items([item]))), 2)
				item.raw_billable_hours = changed
				with self.assertRaisesRegex(FrappeValidationError, "Billing hours changed"):
					_lock_billing_sources(_review_source_items([item]))

	def test_source_lock_rejects_native_invoice_reference(self):
		item = FakeDocument(
			project="PROJ-0001",
			rate=120,
			source_count=1,
			raw_billable_hours=0.2,
			timesheet_detail="ROW-0001",
			source_details_json="",
		)
		with (
			patch(
				"working_time.platform_operations.frappe.db.sql",
				return_value=[_locked_source(sales_invoice="SINV-NATIVE")],
			),
			self.assertRaisesRegex(FrappeValidationError, "native Sales Invoice references"),
		):
			_lock_billing_sources(_review_source_items([item]))

	def test_billing_status_uses_time_billable_instead_of_legacy_billing_model(self):
		detail = FakeDocument(name="ROW-0001", project="PROJ-0001", base_billing_rate=120)
		project = FakeDocument(
			name="PROJ-0001",
			customer="CUST-0001",
			time_billable=1,
			billing_model="Fixed Price",
			billing_rate=120,
			sales_order=None,
		)
		with (
			patch("working_time.platform_operations.frappe.get_doc", return_value=project),
			patch("working_time.platform_operations.frappe.db.get_value", return_value="PROJ-0001"),
		):
			status, context = _billing_status(detail, {})

		self.assertEqual(status, "Eligible")
		self.assertIs(context["project"], project)

		project.time_billable = 0
		project.billing_model = "Time and Material"
		with patch("working_time.platform_operations.frappe.get_doc", return_value=project):
			status, context = _billing_status(detail, {})

		self.assertEqual(status, "Locked")
		self.assertIs(context["project"], project)

	def test_billing_review_sales_order_context_fails_closed(self):
		detail = FakeDocument(name="ROW-0001", project="PROJ-0001", base_billing_rate=120)
		project = FakeDocument(
			name="PROJ-0001",
			customer="CUST-0001",
			company="JITIS",
			time_billable=1,
			billing_rate=120,
			sales_order="SO-0001",
		)
		valid = {
			"name": "SO-0001",
			"customer": "CUST-0001",
			"company": "JITIS",
			"project": "PROJ-0001",
			"docstatus": 1,
		}
		invalid_orders = [
			None,
			{**valid, "customer": "CUST-OTHER"},
			{**valid, "company": "OTHER"},
			{**valid, "project": "PROJ-OTHER"},
			{**valid, "docstatus": 0},
		]

		for sales_order in invalid_orders:
			with self.subTest(sales_order=sales_order):

				def get_value(doctype, name, fields, current_sales_order=sales_order, **kwargs):
					if doctype == "Customer":
						return "PROJ-CANONICAL"
					if doctype == "Sales Order":
						self.assertEqual(name, "SO-0001")
						self.assertEqual(fields, ["name", "customer", "company", "project", "docstatus"])
						self.assertEqual(kwargs, {"as_dict": True})
						return current_sales_order
					raise AssertionError((doctype, name, fields, kwargs))

				with (
					patch("working_time.platform_operations.frappe.get_doc", return_value=project),
					patch("working_time.platform_operations.frappe.db.get_value", side_effect=get_value),
				):
					status, context = _billing_status(detail, {})

				self.assertEqual(status, "Missing Sales Order")
				self.assertIs(context["project"], project)

		project.sales_order = None
		with (
			patch("working_time.platform_operations.frappe.get_doc", return_value=project),
			patch("working_time.platform_operations.frappe.db.get_value", return_value="PROJ-CANONICAL"),
		):
			status, context = _billing_status(detail, {})
		self.assertEqual(status, "Missing Sales Order")
		self.assertIs(context["project"], project)

	def test_project_scoped_billing_review_accepts_permanent_project_without_sales_order(self):
		target_detail = FakeDocument(
			name="ROW-0001",
			base_billing_rate=120,
			project="PROJ-0001",
			task="TASK-0001",
			issue="ISS-0001",
			customer_description="Monthly support",
			description="Internal fallback",
			from_time="2026-08-12 09:00:00",
			hours=0.2,
			billing_hours=0.2,
			is_billable=1,
		)
		other_detail = FakeDocument(
			name="ROW-0002",
			project="PROJ-0002",
			from_time="2026-08-12 10:00:00",
			hours=1,
			billing_hours=1,
			is_billable=1,
		)
		timesheet = FakeDocument(
			name="TS-0001",
			start_date="2026-08-12",
			time_logs=[target_detail, other_detail],
		)
		project = FakeDocument(
			name="PROJ-0001",
			customer="CUST-0001",
			company="JITIS",
			time_billable=1,
			billing_model="Fixed Price",
			billing_rate=120,
			sales_order="SO-STALE",
		)
		review = FakeDocument(name="BR-0001", items=[])

		def get_doc(doctype, name=None):
			if isinstance(doctype, dict):
				review.values = doctype
				for key, value in doctype.items():
					setattr(review, key, value)
				return review
			if doctype == "Project" and name == "PROJ-0001":
				return project
			if doctype == "Timesheet" and name == "TS-0001":
				return timesheet
			raise AssertionError((doctype, name))

		with (
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc) as get_doc_mock,
			patch(
				"working_time.platform_operations.frappe.get_all",
				return_value=[FakeDocument(name="TS-0001")],
			),
			patch("working_time.platform_operations.frappe.db.exists") as exists,
			patch(
				"working_time.platform_operations.frappe.db.get_value",
				return_value="PROJ-0001",
			),
			patch("working_time.platform_operations._claimed_billing_sources", return_value={}),
		):
			result = create_billing_review("2026-08-01", "2026-08-31", project="PROJ-0001")

		self.assertEqual(result, {"name": "BR-0001", "counts": {"Eligible": 1}, "eligible_group_count": 1})
		self.assertEqual(review.values["project"], "PROJ-0001")
		self.assertTrue(review.inserted)
		self.assertEqual(len(review.items), 1)
		item = review.items[0]
		self.assertEqual(item.project, "PROJ-0001")
		self.assertEqual(item.customer, "CUST-0001")
		self.assertIsNone(item.sales_order)
		self.assertEqual(item.status, "Eligible")
		self.assertEqual(item.hours, 0.25)
		self.assertEqual(item.amount, 30)
		self.assertEqual(item.source_count, 1)
		self.assertEqual(json.loads(item.source_details_json)[0]["timesheet_detail"], "ROW-0001")
		self.assertNotIn(
			unittest.mock.call("Project", "PROJ-0002"),
			get_doc_mock.call_args_list,
		)
		exists.assert_not_called()

	def test_invoice_creation_without_sales_order_uses_validated_project_settings(self):
		item = FakeDocument(
			status="Eligible",
			customer="CUST-0001",
			sales_order="SO-STALE",
			project="PROJ-0001",
			task="TASK-0001",
			work_date="2026-08-12",
			hours=0.25,
			rate=120,
			ticket_references="ISS-0001",
			customer_description="Monthly support",
			timesheet_detail="ROW-0001",
			source_details_json='[{"timesheet":"TS-0001","timesheet_detail":"ROW-0001"}]',
			sales_invoice=None,
		)
		review = FakeDocument(name="BR-0001", status="Preview", items=[item])
		project = FakeDocument(
			name="PROJ-0001",
			customer="CUST-0001",
			company="JITIS",
			time_billable=1,
			billing_model="Fixed Price",
			billing_rate=999,
			sales_order="SO-STALE",
		)
		invoice = FakeDocument(name="SINV-0001")
		doctypes = []

		def get_doc(doctype, name=None):
			doctypes.append(doctype if isinstance(doctype, str) else doctype["doctype"])
			if isinstance(doctype, dict):
				invoice.values = doctype
				return invoice
			if doctype == "Billing Review":
				return review
			if doctype == "Project":
				self.assertEqual(name, "PROJ-0001")
				return project
			raise AssertionError((doctype, name))

		def get_value(doctype, name, fieldname):
			if doctype == "Customer" and name == "CUST-0001":
				if fieldname == "customer_project":
					return "PROJ-0001"
				if fieldname == "default_currency":
					return "USD"
			if doctype == "Company" and name == "JITIS" and fieldname == "default_currency":
				return "EUR"
			raise AssertionError((doctype, name, fieldname))

		with (
			patch(
				"working_time.platform_operations._settings",
				return_value=FakeDocument(default_time_billing_item="TIME"),
			),
			patch(
				"working_time.platform_operations._lock_billing_sources",
				return_value={"ROW-0001": _locked_source()},
			),
			patch("working_time.platform_operations._claimed_billing_sources", return_value={}),
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
			patch("working_time.platform_operations.frappe.get_all", return_value=[]),
			patch(
				"working_time.platform_operations.frappe.db.get_value", side_effect=get_value
			) as get_value_mock,
		):
			result = create_billing_invoice_drafts("BR-0001")

		self.assertNotIn("Sales Order", doctypes)
		self.assertEqual(result, {"name": "BR-0001", "sales_invoices": ["SINV-0001"], "created": True})
		self.assertEqual(invoice.values["customer"], "CUST-0001")
		self.assertEqual(invoice.values["company"], "JITIS")
		self.assertEqual(invoice.values["currency"], "EUR")
		self.assertNotIn(
			call("Customer", "CUST-0001", "default_currency"),
			get_value_mock.call_args_list,
		)
		self.assertIn(
			call("Company", "JITIS", "default_currency"),
			get_value_mock.call_args_list,
		)
		self.assertEqual(len(invoice.values["items"]), 1)
		invoice_item = invoice.values["items"][0]
		self.assertEqual(invoice_item["item_code"], "TIME")
		self.assertEqual(invoice_item["qty"], 0.25)
		self.assertEqual(invoice_item["rate"], 120)
		self.assertEqual(invoice_item["project"], "PROJ-0001")
		self.assertNotIn("sales_order", invoice_item)
		self.assertNotIn("so_detail", invoice_item)
		self.assertEqual(invoice.values["timesheets"][0]["timesheet_detail"], "ROW-0001")
		self.assertEqual(invoice.values["timesheets"][0]["billing_hours"], 0.2)
		self.assertTrue(invoice.inserted)
		self.assertEqual(item.status, "Draft Created")
		self.assertEqual(item.sales_invoice, "SINV-0001")
		self.assertEqual(review.status, "Draft Created")
		self.assertTrue(review.saved)

	def test_invoice_creation_without_sales_order_requires_company_currency(self):
		item = FakeDocument(
			status="Eligible",
			customer="CUST-0001",
			sales_order=None,
			project="PROJ-0001",
			hours=0.25,
			rate=120,
			timesheet_detail="ROW-0001",
			source_details_json='[{"timesheet":"TS-0001","timesheet_detail":"ROW-0001"}]',
			sales_invoice=None,
		)
		review = FakeDocument(name="BR-0001", status="Preview", items=[item])
		project = FakeDocument(
			name="PROJ-0001",
			customer="CUST-0001",
			company="JITIS",
			time_billable=1,
			billing_rate=120,
		)

		def get_doc(doctype, name=None):
			if doctype == "Billing Review":
				return review
			if doctype == "Project":
				return project
			raise AssertionError((doctype, name))

		def get_value(doctype, name, fieldname):
			if doctype == "Customer" and name == "CUST-0001" and fieldname == "customer_project":
				return "PROJ-0001"
			if doctype == "Company" and name == "JITIS" and fieldname == "default_currency":
				return None
			raise AssertionError((doctype, name, fieldname))

		with (
			patch(
				"working_time.platform_operations._settings",
				return_value=FakeDocument(default_time_billing_item="TIME"),
			),
			patch(
				"working_time.platform_operations._lock_billing_sources",
				return_value={"ROW-0001": _locked_source()},
			),
			patch("working_time.platform_operations._claimed_billing_sources", return_value={}),
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
			patch("working_time.platform_operations.frappe.get_all", return_value=[]),
			patch("working_time.platform_operations.frappe.db.get_value", side_effect=get_value),
			self.assertRaisesRegex(
				FrappeValidationError,
				"Set a Default Currency for company JITIS before creating invoice drafts",
			),
		):
			create_billing_invoice_drafts("BR-0001")

		self.assertEqual(item.status, "Eligible")
		self.assertIsNone(item.sales_invoice)
		self.assertEqual(review.status, "Preview")
		self.assertFalse(hasattr(review, "saved"))

	def test_invoice_creation_retry_reuses_linked_drafts_after_row_lock(self):
		item = FakeDocument(status="Draft Created", sales_invoice="SINV-0001")
		review = FakeDocument(name="BR-0001", status="Draft Created", items=[item])
		with (
			patch(
				"working_time.platform_operations._settings",
				return_value=FakeDocument(default_time_billing_item="TIME"),
			),
			patch("working_time.platform_operations.frappe.db.sql") as sql,
			patch("working_time.platform_operations.frappe.get_doc", return_value=review),
		):
			result = create_billing_invoice_drafts("BR-0001")

		self.assertEqual(
			sql.call_args.args,
			("select name from `tabBilling Review` where name=%s for update", ("BR-0001",)),
		)
		self.assertEqual(
			result,
			{
				"name": "BR-0001",
				"sales_invoices": ["SINV-0001"],
				"created": False,
			},
		)

	def test_parallel_review_loser_observes_claim_after_source_lock(self):
		item = FakeDocument(
			status="Eligible",
			customer="CUST-0001",
			project="PROJ-0001",
			hours=0.25,
			rate=120,
			timesheet_detail="ROW-0001",
			source_count=1,
			source_details_json='[{"timesheet_detail":"ROW-0001"}]',
			sales_invoice=None,
		)
		review = FakeDocument(name="BR-LOSER", status="Preview", items=[item])
		events = []

		def lock_sources(source_items):
			events.append(("lock", sorted(source_items)))
			return {"ROW-0001": _locked_source()}

		def current_claims(exclude_review=None, *, for_update=False):
			events.append(("claims", exclude_review, for_update))
			return {"ROW-0001": "Draft Created"}

		with (
			patch(
				"working_time.platform_operations._settings",
				return_value=FakeDocument(default_time_billing_item="TIME"),
			),
			patch("working_time.platform_operations._lock_billing_sources", side_effect=lock_sources),
			patch(
				"working_time.platform_operations._claimed_billing_sources",
				side_effect=current_claims,
			),
			patch("working_time.platform_operations.frappe.db.sql"),
			patch("working_time.platform_operations.frappe.get_doc", return_value=review) as get_doc,
			self.assertRaisesRegex(FrappeValidationError, "assigned to another draft or invoice"),
		):
			create_billing_invoice_drafts("BR-LOSER")

		self.assertEqual(
			events,
			[("lock", ["ROW-0001"]), ("claims", "BR-LOSER", True)],
		)
		get_doc.assert_called_once_with("Billing Review", "BR-LOSER")
		self.assertEqual(review.status, "Preview")
		self.assertEqual(item.status, "Eligible")
		self.assertIsNone(item.sales_invoice)

	def test_invoice_creation_marks_review_as_draft_created(self):
		item = FakeDocument(
			status="Eligible",
			customer="CUST-0001",
			sales_order="SO-0001",
			project="PROJ-0001",
			task="TASK-0001",
			work_date="2026-08-01",
			hours=0.25,
			rate=120,
			timesheet_detail="ROW-0001",
			source_details_json='[{"timesheet":"TS-0001","timesheet_detail":"ROW-0001"}]',
			sales_invoice=None,
		)
		review = FakeDocument(name="BR-0001", status="Preview", items=[item])
		project = FakeDocument(
			name="PROJ-0001",
			customer="CUST-0001",
			company="JITIS",
			time_billable=1,
			billing_rate=120,
			sales_order="SO-0001",
		)
		sales_order = FakeDocument(
			name="SO-0001",
			customer="CUST-0001",
			company="JITIS",
			project="PROJ-0001",
			docstatus=1,
			currency="EUR",
			items=[
				FakeDocument(
					name="SOI-0001",
					item_code="TIME",
					rate=120,
					uom="Hour",
					conversion_factor=1,
				),
				FakeDocument(name="SOI-0002", item_code="OTHER"),
			],
		)
		invoice = FakeDocument(name="SINV-0001")

		def get_doc(doctype, name=None):
			if isinstance(doctype, dict):
				invoice.values = doctype
				return invoice
			if doctype == "Billing Review":
				return review
			if doctype == "Project":
				return project
			if doctype == "Sales Order":
				return sales_order
			raise AssertionError(doctype)

		with (
			patch(
				"working_time.platform_operations._settings",
				return_value=FakeDocument(default_time_billing_item="TIME"),
			),
			patch(
				"working_time.platform_operations._lock_billing_sources",
				return_value={"ROW-0001": _locked_source()},
			),
			patch("working_time.platform_operations._claimed_billing_sources", return_value={}),
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
			patch("working_time.platform_operations.frappe.get_all", return_value=[]),
			patch(
				"working_time.platform_operations.frappe.db.get_value",
				side_effect=lambda doctype, *args, **kwargs: (
					"EUR" if doctype == "Company" else "PROJ-CANONICAL"
				),
			),
		):
			result = create_billing_invoice_drafts("BR-0001")

		self.assertEqual(result["sales_invoices"], ["SINV-0001"])
		self.assertTrue(result["created"])
		self.assertEqual(review.status, "Draft Created")
		self.assertEqual(item.status, "Draft Created")
		self.assertEqual(item.sales_invoice, "SINV-0001")
		self.assertEqual(invoice.values["items"][0]["qty"], 0.25)
		self.assertEqual(invoice.values["items"][0]["sales_order"], "SO-0001")
		self.assertEqual(invoice.values["items"][0]["so_detail"], "SOI-0001")
		self.assertEqual(invoice.values["timesheets"][0]["timesheet_detail"], "ROW-0001")

	def test_invoice_draft_revalidates_submitted_sales_order_context(self):
		item = FakeDocument(
			status="Eligible",
			customer="CUST-0001",
			sales_order="SO-0001",
			project="PROJ-0001",
			work_date="2026-08-01",
			hours=0.25,
			rate=120,
			timesheet_detail="ROW-0001",
			source_details_json='[{"timesheet":"TS-0001","timesheet_detail":"ROW-0001"}]',
			sales_invoice=None,
		)
		review = FakeDocument(name="BR-0001", status="Preview", items=[item])
		project = FakeDocument(
			name="PROJ-0001",
			customer="CUST-0001",
			company="JITIS",
			time_billable=1,
			billing_rate=120,
			sales_order="SO-0001",
		)
		valid = {
			"name": "SO-0001",
			"customer": "CUST-0001",
			"company": "JITIS",
			"project": "PROJ-0001",
			"docstatus": 1,
			"currency": "EUR",
			"items": [],
		}
		invalid_orders = [
			{**valid, "customer": "CUST-OTHER"},
			{**valid, "company": "OTHER"},
			{**valid, "project": "PROJ-OTHER"},
			{**valid, "docstatus": 0},
		]

		for values in invalid_orders:
			with self.subTest(values=values):
				sales_order = FakeDocument(**values)

				def get_doc(doctype, name=None, current_sales_order=sales_order):
					if doctype == "Billing Review":
						return review
					if doctype == "Project":
						return project
					if doctype == "Sales Order":
						return current_sales_order
					if isinstance(doctype, dict):
						self.fail("Sales Invoice must not be built before Sales Order context validation")
					raise AssertionError((doctype, name))

				with (
					patch(
						"working_time.platform_operations._settings",
						return_value=FakeDocument(default_time_billing_item="TIME"),
					),
					patch(
						"working_time.platform_operations._lock_billing_sources",
						return_value={"ROW-0001": _locked_source()},
					),
					patch("working_time.platform_operations._claimed_billing_sources", return_value={}),
					patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
					patch("working_time.platform_operations.frappe.get_all", return_value=[]),
					patch(
						"working_time.platform_operations.frappe.db.get_value",
						return_value="PROJ-CANONICAL",
					),
					self.assertRaisesRegex(FrappeValidationError, "customer, company and project context"),
				):
					create_billing_invoice_drafts("BR-0001")

				self.assertEqual(review.status, "Preview")
				self.assertEqual(item.status, "Eligible")
				self.assertIsNone(item.sales_invoice)

	def test_invoice_creation_rejects_sales_order_rate_or_currency_drift_before_building_invoice(self):
		item = FakeDocument(
			status="Eligible",
			customer="CUST-0001",
			sales_order="SO-0001",
			project="PROJ-0001",
			task=None,
			work_date="2026-08-01",
			hours=0.25,
			rate=120,
			timesheet_detail="ROW-0001",
			source_details_json='[{"timesheet":"TS-0001","timesheet_detail":"ROW-0001"}]',
			sales_invoice=None,
		)
		review = FakeDocument(name="BR-0001", status="Preview", items=[item])
		project = FakeDocument(
			name="PROJ-0001",
			customer="CUST-0001",
			company="JITIS",
			time_billable=1,
			billing_rate=120,
			sales_order="SO-0001",
		)
		sales_order = FakeDocument(
			name="SO-0001",
			customer="CUST-0001",
			company="JITIS",
			project="PROJ-0001",
			docstatus=1,
			currency="EUR",
			items=[
				FakeDocument(
					name="SOI-0001",
					item_code="TIME",
					rate=119,
					uom="Hour",
					conversion_factor=1,
				)
			],
		)

		def get_doc(doctype, name=None):
			if doctype == "Billing Review":
				return review
			if doctype == "Project":
				return project
			if doctype == "Sales Order":
				return sales_order
			if isinstance(doctype, dict):
				self.fail("Sales Invoice must not be built before rate validation")
			raise AssertionError(doctype)

		for currency, rate, message in (
			("EUR", 119, "rates must equal the Sales Order"),
			("USD", 120, "company currency"),
		):
			sales_order.currency = currency
			sales_order.items[0].rate = rate
			with (
				self.subTest(currency=currency, rate=rate),
				patch(
					"working_time.platform_operations._settings",
					return_value=FakeDocument(default_time_billing_item="TIME"),
				),
				patch(
					"working_time.platform_operations._lock_billing_sources",
					return_value={"ROW-0001": _locked_source()},
				),
				patch("working_time.platform_operations._claimed_billing_sources", return_value={}),
				patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
				patch("working_time.platform_operations.frappe.get_all", return_value=[]),
				patch(
					"working_time.platform_operations.frappe.db.get_value",
					side_effect=lambda doctype, *args, **kwargs: (
						"EUR" if doctype == "Company" else "PROJ-CANONICAL"
					),
				),
				self.assertRaisesRegex(FrappeValidationError, message),
			):
				create_billing_invoice_drafts("BR-0001")

		self.assertEqual(review.status, "Preview")
		self.assertIsNone(item.sales_invoice)

	def test_invoice_creation_rejects_missing_or_ambiguous_time_billing_item(self):
		item = FakeDocument(
			status="Eligible",
			customer="CUST-0001",
			sales_order="SO-0001",
			project="PROJ-0001",
			task=None,
			work_date="2026-08-01",
			hours=0.25,
			rate=120,
			timesheet_detail="ROW-0001",
			source_details_json='[{"timesheet":"TS-0001","timesheet_detail":"ROW-0001"}]',
			sales_invoice=None,
		)
		review = FakeDocument(name="BR-0001", status="Preview", items=[item])
		project = FakeDocument(
			name="PROJ-0001",
			customer="CUST-0001",
			company="JITIS",
			time_billable=1,
			billing_rate=120,
			sales_order="SO-0001",
		)

		for sales_order_items in (
			[FakeDocument(name="SOI-OTHER", item_code="OTHER")],
			[
				FakeDocument(name="SOI-0001", item_code="TIME"),
				FakeDocument(name="SOI-0002", item_code="TIME"),
			],
		):
			with self.subTest(sales_order_items=sales_order_items):
				sales_order = FakeDocument(
					name="SO-0001",
					customer="CUST-0001",
					company="JITIS",
					project="PROJ-0001",
					docstatus=1,
					currency="EUR",
					items=sales_order_items,
				)

				def get_doc(doctype, name=None, current_sales_order=sales_order):
					if doctype == "Billing Review":
						return review
					if doctype == "Project":
						return project
					if doctype == "Sales Order":
						return current_sales_order
					if isinstance(doctype, dict):
						self.fail("Sales Invoice must not be built before Sales Order Item validation")
					raise AssertionError(doctype)

				with (
					patch(
						"working_time.platform_operations._settings",
						return_value=FakeDocument(default_time_billing_item="TIME"),
					),
					patch(
						"working_time.platform_operations._lock_billing_sources",
						return_value={"ROW-0001": _locked_source()},
					),
					patch(
						"working_time.platform_operations._claimed_billing_sources",
						return_value={},
					),
					patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
					patch("working_time.platform_operations.frappe.get_all", return_value=[]),
					patch(
						"working_time.platform_operations.frappe.db.get_value",
						side_effect=lambda doctype, *args, **kwargs: (
							"EUR" if doctype == "Company" else "PROJ-CANONICAL"
						),
					),
					self.assertRaisesRegex(FrappeValidationError, "exactly one row"),
				):
					create_billing_invoice_drafts("BR-0001")

				self.assertEqual(review.status, "Preview")
				self.assertIsNone(item.sales_invoice)

	def test_project_time_invoice_wrapper_returns_exactly_one_draft(self):
		with (
			patch(
				"working_time.platform_operations.create_billing_review",
				return_value={"name": "BR-0001"},
			) as create_review,
			patch(
				"working_time.platform_operations.create_billing_invoice_drafts",
				return_value={"sales_invoices": ["SINV-0001"]},
			) as create_drafts,
			patch("working_time.platform_operations.frappe.db.savepoint", create=True) as savepoint,
			patch("working_time.platform_operations.frappe.db.rollback", create=True) as rollback,
			patch("working_time.platform_operations.frappe.db.commit", create=True) as commit,
		):
			result = create_project_time_invoice_draft("PROJ-0001", "2026-08-01", "2026-08-31")

		self.assertEqual(result, {"review": "BR-0001", "sales_invoices": ["SINV-0001"]})
		create_review.assert_called_once_with("2026-08-01", "2026-08-31", project="PROJ-0001")
		create_drafts.assert_called_once_with("BR-0001")
		savepoint.assert_called_once_with("project_time_invoice_draft")
		rollback.assert_not_called()
		commit.assert_not_called()

	def test_project_time_invoice_wrapper_requires_project_filter(self):
		with (
			patch("working_time.platform_operations.create_billing_review") as create_review,
			patch("working_time.platform_operations.frappe.db.savepoint", create=True) as savepoint,
			self.assertRaisesRegex(FrappeValidationError, "Project is required"),
		):
			create_project_time_invoice_draft("  ", "2026-08-01", "2026-08-31")

		create_review.assert_not_called()
		savepoint.assert_not_called()

	def test_project_time_invoice_wrapper_rolls_back_unexpected_invoice_count(self):
		for invoices in ([], ["SINV-0001", "SINV-0002"]):
			with self.subTest(invoices=invoices):
				with (
					patch(
						"working_time.platform_operations.create_billing_review",
						return_value={"name": "BR-0001"},
					),
					patch(
						"working_time.platform_operations.create_billing_invoice_drafts",
						return_value={"sales_invoices": invoices},
					),
					patch("working_time.platform_operations.frappe.db.savepoint", create=True) as savepoint,
					patch("working_time.platform_operations.frappe.db.rollback", create=True) as rollback,
					patch("working_time.platform_operations.frappe.db.commit", create=True) as commit,
					self.assertRaisesRegex(
						FrappeValidationError,
						"exactly one draft Sales Invoice",
					),
				):
					create_project_time_invoice_draft("PROJ-0001", "2026-08-01", "2026-08-31")

				savepoint.assert_called_once_with("project_time_invoice_draft")
				rollback.assert_called_once_with(save_point="project_time_invoice_draft")
				commit.assert_not_called()

	def test_submitted_invoice_synchronizes_review_once_and_stays_idempotent(self):
		item = FakeDocument(status="Draft Created", sales_invoice="SINV-0001")
		review = FakeDocument(
			name="BR-0001",
			status="Draft Created",
			items=[item],
			result_json='{"sales_invoices":["SINV-0001"],"status":"Draft Created"}',
			error="",
			created_invoice_count=1,
		)
		with (
			patch(
				"working_time.platform_operations.frappe.get_all",
				return_value=[FakeDocument(name="SINV-0001", docstatus=1)],
			),
			patch.object(review, "save", wraps=review.save) as save,
		):
			first = _synchronize_billing_review_status(review)
			second = _synchronize_billing_review_status(review)

		self.assertEqual(first["status"], "Invoiced")
		self.assertEqual(second, first)
		self.assertEqual(review.status, "Invoiced")
		self.assertEqual(item.status, "Invoiced")
		self.assertEqual(save.call_count, 1)
		self.assertIn("finalized_at", json.loads(review.result_json))

	def test_cancelled_or_missing_invoice_marks_review_failed_but_keeps_source_claimed(self):
		for invoice_rows in (
			[FakeDocument(name="SINV-0001", docstatus=2)],
			[],
		):
			with self.subTest(invoice_rows=invoice_rows):
				item = FakeDocument(status="Draft Created", sales_invoice="SINV-0001")
				review = FakeDocument(
					name="BR-0001",
					status="Draft Created",
					items=[item],
					result_json="{}",
					error="",
					created_invoice_count=1,
				)
				with patch(
					"working_time.platform_operations.frappe.get_all",
					return_value=invoice_rows,
				):
					result = _synchronize_billing_review_status(review)

				self.assertEqual(result["status"], "Failed")
				self.assertEqual(review.status, "Failed")
				self.assertEqual(item.status, "Already Invoiced")
				self.assertIn("SINV-0001", review.error)

	def test_sales_invoice_event_locks_and_synchronizes_linked_reviews(self):
		review = FakeDocument(name="BR-0001")
		with (
			patch(
				"working_time.platform_operations.frappe.get_all",
				return_value=["BR-0001", "BR-0001"],
			) as get_all,
			patch("working_time.platform_operations.frappe.db.sql") as sql,
			patch("working_time.platform_operations.frappe.get_doc", return_value=review),
			patch("working_time.platform_operations._synchronize_billing_review_status") as sync,
		):
			synchronize_billing_reviews_for_invoice(FakeDocument(name="SINV-0001"))

		get_all.assert_called_once_with(
			"Billing Review Item",
			filters={"sales_invoice": "SINV-0001"},
			pluck="parent",
		)
		self.assertEqual(
			sql.call_args.args,
			("select name from `tabBilling Review` where name=%s for update", ("BR-0001",)),
		)
		sync.assert_called_once_with(review)

	def test_sales_invoice_hooks_keep_billing_review_status_current(self):
		from working_time.hooks import doc_events

		self.assertEqual(
			doc_events["Sales Invoice"]["before_submit"],
			"working_time.platform_operations.validate_billing_review_invoice_sources",
		)
		self.assertEqual(
			doc_events["Sales Invoice"]["on_submit"],
			"working_time.platform_operations.synchronize_billing_reviews_for_invoice",
		)
		self.assertEqual(
			doc_events["Sales Invoice"]["on_cancel"],
			"working_time.platform_operations.synchronize_billing_reviews_for_invoice",
		)

	def test_linked_invoice_submit_requires_exact_native_timesheet_sources(self):
		item = FakeDocument(
			project="PROJ-0001",
			timesheet_detail="ROW-0001",
			source_count=1,
			source_details_json='[{"timesheet_detail":"ROW-0001"}]',
			raw_billable_hours=0.2,
		)
		invoice = FakeDocument(
			name="SINV-0001",
			timesheets=[FakeDocument(time_sheet="TS-0001", timesheet_detail="ROW-0001")],
		)
		locked = {"ROW-0001": _locked_source()}
		with (
			patch("working_time.platform_operations.frappe.get_all", return_value=[item]) as get_all,
			patch(
				"working_time.platform_operations._lock_billing_sources",
				return_value=locked,
			) as lock_sources,
		):
			validate_billing_review_invoice_sources(invoice)

		get_all.assert_called_once_with(
			"Billing Review Item",
			filters={"sales_invoice": "SINV-0001"},
			fields=[
				"timesheet_detail",
				"source_details_json",
				"source_count",
				"project",
				"raw_billable_hours",
				"rate",
			],
		)
		lock_sources.assert_called_once()

	def test_linked_invoice_submit_rejects_removed_or_duplicate_timesheet_sources(self):
		item = FakeDocument(
			project="PROJ-0001",
			timesheet_detail="ROW-0001",
			source_count=1,
			source_details_json="",
			raw_billable_hours=0.2,
		)
		locked = {"ROW-0001": _locked_source()}
		for timesheets in (
			[],
			[
				FakeDocument(time_sheet="TS-0001", timesheet_detail="ROW-0001"),
				FakeDocument(time_sheet="TS-0001", timesheet_detail="ROW-0001"),
			],
		):
			with (
				self.subTest(timesheets=timesheets),
				patch("working_time.platform_operations.frappe.get_all", return_value=[item]),
				patch(
					"working_time.platform_operations._lock_billing_sources",
					return_value=locked,
				),
				self.assertRaisesRegex(FrappeValidationError, "no longer match"),
			):
				validate_billing_review_invoice_sources(FakeDocument(name="SINV-0001", timesheets=timesheets))

	def test_billing_review_finalization_requires_submitted_invoices(self):
		item = FakeDocument(status="Draft Created", sales_invoice="SINV-0001")
		review = FakeDocument(name="BR-0001", status="Draft Created", items=[item])
		with (
			patch("working_time.platform_operations.frappe.get_doc", return_value=review),
			patch(
				"working_time.platform_operations.frappe.get_all",
				return_value=[FakeDocument(name="SINV-0001", docstatus=0)],
			),
			patch("working_time.platform_operations.frappe.db.get_value", return_value=0),
			self.assertRaises(FrappeValidationError),
		):
			finalize_billing_review("BR-0001")

		self.assertEqual(review.status, "Draft Created")
		self.assertEqual(item.status, "Draft Created")

	def test_billing_review_finalizes_after_manual_invoice_submission(self):
		item = FakeDocument(status="Draft Created", sales_invoice="SINV-0001")
		review = FakeDocument(name="BR-0001", status="Draft Created", items=[item])
		with (
			patch("working_time.platform_operations.frappe.get_doc", return_value=review),
			patch(
				"working_time.platform_operations.frappe.get_all",
				return_value=[FakeDocument(name="SINV-0001", docstatus=1)],
			),
		):
			result = finalize_billing_review("BR-0001")

		self.assertEqual(result["status"], "Invoiced")
		self.assertEqual(review.status, "Invoiced")
		self.assertEqual(item.status, "Invoiced")

	def test_billable_ui_only_offers_non_billable_or_fully_billable(self):
		doctype_path = (
			Path(__file__).parent / "working_time" / "doctype" / "working_time_log" / "working_time_log.json"
		)
		metadata = json.loads(doctype_path.read_text())
		fields = {field["fieldname"]: field for field in metadata["fields"] if "fieldname" in field}

		self.assertEqual(fields["billable"]["options"].splitlines(), ["0%", "100%"])
