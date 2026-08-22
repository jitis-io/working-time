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
	frappe.has_permission = lambda *args, **kwargs: True
	frappe.session = types.SimpleNamespace(user="test@example.com")
	frappe_utils = types.ModuleType("frappe.utils")
	frappe_utils.nowdate = lambda: "2026-08-20"
	frappe.utils = frappe_utils
	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = frappe_utils


_bootstrap_frappe_stub()

import frappe

FrappeValidationError = getattr(frappe, "ValidationError", RuntimeError)

from working_time.platform_operations import (
	_aggregate_billing_sources,
	_billing_status,
	_round_billable_hours,
	_sales_order_time_billing_row,
	create_billing_invoice_drafts,
	create_billing_review,
	create_project_time_invoice_draft,
	finalize_billing_review,
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

	def test_claimed_billing_source_wins_over_changed_project_configuration(self):
		detail = FakeDocument(name="ROW-0001", project="PROJ-0001")
		with patch("working_time.platform_operations.frappe.get_doc") as get_doc:
			status, context = _billing_status(detail, {"ROW-0001": "Draft Created"})

		self.assertEqual(status, "Already Drafted")
		self.assertEqual(context, {})
		get_doc.assert_not_called()

	def test_billing_status_uses_time_billable_instead_of_legacy_billing_model(self):
		detail = FakeDocument(name="ROW-0001", project="PROJ-0001")
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
			patch("working_time.platform_operations.frappe.db.get_value", return_value=None),
			patch("working_time.platform_operations.frappe.db.exists") as exists,
		):
			status, context = _billing_status(detail, {})

		self.assertEqual(status, "Eligible")
		self.assertIs(context["project"], project)
		exists.assert_not_called()

		project.time_billable = 0
		project.billing_model = "Time and Material"
		with patch("working_time.platform_operations.frappe.get_doc", return_value=project):
			status, context = _billing_status(detail, {})

		self.assertEqual(status, "Locked")
		self.assertIs(context["project"], project)

	def test_project_scoped_billing_review_accepts_permanent_project_without_sales_order(self):
		target_detail = FakeDocument(
			name="ROW-0001",
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
			billing_rate=120,
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
			company="JITIS",
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
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
			patch("working_time.platform_operations.frappe.get_all", return_value=[]),
			patch(
				"working_time.platform_operations.frappe.db.get_value",
				return_value="PROJ-CANONICAL",
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

	def test_invoice_creation_rejects_rate_drift_before_building_invoice(self):
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
			company="JITIS",
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

		with (
			patch(
				"working_time.platform_operations._settings",
				return_value=FakeDocument(default_time_billing_item="TIME"),
			),
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
			patch("working_time.platform_operations.frappe.get_all", return_value=[]),
			patch(
				"working_time.platform_operations.frappe.db.get_value",
				return_value="PROJ-CANONICAL",
			),
			self.assertRaises(FrappeValidationError),
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
					name="SO-0001", company="JITIS", currency="EUR", items=sales_order_items
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
					patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
					patch("working_time.platform_operations.frappe.get_all", return_value=[]),
					patch(
						"working_time.platform_operations.frappe.db.get_value",
						return_value="PROJ-CANONICAL",
					),
					self.assertRaises(FrappeValidationError),
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

	def test_billing_review_finalization_requires_submitted_invoices(self):
		item = FakeDocument(status="Draft Created", sales_invoice="SINV-0001")
		review = FakeDocument(name="BR-0001", status="Draft Created", items=[item])
		with (
			patch("working_time.platform_operations.frappe.get_doc", return_value=review),
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
			patch("working_time.platform_operations.frappe.db.get_value", return_value=1),
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
