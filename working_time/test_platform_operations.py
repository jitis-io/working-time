import json
import sys
import types
import unittest
from pathlib import Path
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
	frappe.ValidationError = RuntimeError
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.only_for = lambda *args, **kwargs: None
	frappe.RetryBackgroundJobError = type("RetryBackgroundJobError", (Exception,), {})
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
	frappe.get_single = lambda *args, **kwargs: None
	frappe.enqueue = lambda *args, **kwargs: None
	sys.modules["frappe"] = frappe


_bootstrap_frappe_stub()

import frappe

FrappeValidationError = getattr(frappe, "ValidationError", RuntimeError)

from working_time.platform_operations import (
	_aggregate_billing_sources,
	_billing_status,
	_ensure_erpnext_project,
	_provisioning_preview,
	_round_billable_hours,
	_sales_order_project_name,
	_sales_order_time_billing_row,
	_teams_adaptive_card,
	confirm_customer_project_provisioning,
	create_billing_invoice_drafts,
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


class TestPlatformOperations(unittest.TestCase):
	def test_customer_project_provisioning_is_erpnext_only(self):
		preview = _provisioning_preview(
			FakeDocument(
				name="SO-0001",
				customer="CUST-0001",
				customer_name="Example GmbH",
				items=[
					FakeDocument(
						name="SOI-0001",
						item_code="TIME",
						rate=119,
						uom="Hour",
						conversion_factor=1,
					)
				],
			),
			"TIME",
		)

		self.assertEqual(
			preview,
			{
				"sales_order": "SO-0001",
				"customer": "CUST-0001",
				"erpnext_project": "Example GmbH — SO-0001",
				"billing_models": [
					"Non-billable",
					"Time and Material",
					"Fixed Price",
					"Recurring",
				],
				"time_billing_item": "TIME",
				"time_billing_item_match_count": 1,
				"time_billing_item_row": "SOI-0001",
				"suggested_billing_rate": 119,
			},
		)

	def test_time_and_material_confirmation_persists_selected_model_and_rate(self):
		provisioning = FakeDocument(
			name="CPP-0001",
			sales_order="SO-0001",
			status="Preview",
			billing_model=None,
			billing_rate=0,
			preview_json="{}",
			flags=FakeDocument(),
		)
		sales_order = FakeDocument(
			name="SO-0001",
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
			if doctype == "Customer Project Provisioning":
				return provisioning
			if doctype == "Sales Order":
				return sales_order
			raise AssertionError(doctype)

		with (
			patch(
				"working_time.platform_operations._settings",
				return_value=FakeDocument(default_time_billing_item="TIME"),
			),
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
		):
			result = confirm_customer_project_provisioning(
				"CPP-0001", billing_model="Time and Material", billing_rate="119"
			)

		self.assertEqual(result["status"], "Queued")
		self.assertEqual(provisioning.status, "Queued")
		self.assertEqual(provisioning.billing_model, "Time and Material")
		self.assertEqual(provisioning.billing_rate, 119)
		self.assertEqual(json.loads(provisioning.preview_json)["billing_rate"], 119)

	def test_time_and_material_confirmation_rejects_non_positive_rate(self):
		provisioning = FakeDocument(
			name="CPP-0001",
			sales_order="SO-0001",
			status="Preview",
			billing_model=None,
			billing_rate=0,
			preview_json="{}",
			flags=FakeDocument(),
		)
		sales_order = FakeDocument(
			name="SO-0001",
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
			return provisioning if doctype == "Customer Project Provisioning" else sales_order

		with (
			patch(
				"working_time.platform_operations._settings",
				return_value=FakeDocument(default_time_billing_item="TIME"),
			),
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
			self.assertRaises(FrappeValidationError),
		):
			confirm_customer_project_provisioning(
				"CPP-0001", billing_model="Time and Material", billing_rate=0
			)

		self.assertEqual(provisioning.status, "Preview")
		self.assertIsNone(provisioning.billing_model)

	def test_project_creation_uses_confirmed_billing_values(self):
		provisioning = FakeDocument(billing_model="Fixed Price", billing_rate=0)
		sales_order = FakeDocument(
			name="SO-0001",
			customer="CUST-0001",
			customer_name="Example GmbH",
		)
		project = FakeDocument(name="PROJ-0001")

		def get_doc(doctype):
			self.assertIsInstance(doctype, dict)
			project.values = doctype
			return project

		with (
			patch("working_time.platform_operations.frappe.db.get_value", return_value=None),
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
		):
			name = _ensure_erpnext_project(provisioning, sales_order)

		self.assertEqual(name, "PROJ-0001")
		self.assertEqual(project.values["billing_model"], "Fixed Price")
		self.assertEqual(project.values["billing_rate"], 0)

	def test_existing_project_conflicts_abort_provisioning(self):
		provisioning = FakeDocument(billing_model="Time and Material", billing_rate=119)
		sales_order = FakeDocument(
			name="SO-0001",
			customer="CUST-0001",
			customer_name="Example GmbH",
		)
		existing = FakeDocument(
			name="PROJ-0001",
			customer="CUST-OTHER",
			billing_model="Fixed Price",
			billing_rate=0,
		)

		with (
			patch("working_time.platform_operations.frappe.db.get_value", return_value=existing),
			self.assertRaises(FrappeValidationError),
		):
			_ensure_erpnext_project(provisioning, sales_order)

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

	def test_time_and_material_rate_must_equal_sales_order_rate(self):
		provisioning = FakeDocument(
			name="CPP-0001",
			sales_order="SO-0001",
			status="Preview",
			billing_model=None,
			billing_rate=0,
			preview_json="{}",
			flags=FakeDocument(),
		)
		sales_order = FakeDocument(
			name="SO-0001",
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
			return provisioning if doctype == "Customer Project Provisioning" else sales_order

		with (
			patch(
				"working_time.platform_operations._settings",
				return_value=FakeDocument(default_time_billing_item="TIME"),
			),
			patch("working_time.platform_operations.frappe.get_doc", side_effect=get_doc),
			self.assertRaises(FrappeValidationError),
		):
			confirm_customer_project_provisioning(
				"CPP-0001", billing_model="Time and Material", billing_rate=120
			)

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
					self.assertRaises(FrappeValidationError),
				):
					create_billing_invoice_drafts("BR-0001")

				self.assertEqual(review.status, "Preview")
				self.assertIsNone(item.sales_invoice)

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

	def test_teams_webhook_is_long_text_not_password(self):
		doctype_path = (
			Path(__file__).parent
			/ "working_time"
			/ "doctype"
			/ "platform_operations_settings"
			/ "platform_operations_settings.json"
		)
		metadata = json.loads(doctype_path.read_text())
		fields = {field["fieldname"]: field for field in metadata["fields"]}

		self.assertEqual(fields["teams_webhook_url"]["fieldtype"], "Small Text")
		self.assertNotIn("keycloak_client_secret", fields)

	def test_billable_ui_only_offers_non_billable_or_fully_billable(self):
		doctype_path = (
			Path(__file__).parent / "working_time" / "doctype" / "working_time_log" / "working_time_log.json"
		)
		metadata = json.loads(doctype_path.read_text())
		fields = {field["fieldname"]: field for field in metadata["fields"] if "fieldname" in field}

		self.assertEqual(fields["billable"]["options"].splitlines(), ["0%", "100%"])

	def test_teams_alert_uses_workflow_adaptive_card_schema(self):
		payload = _teams_adaptive_card(
			"customer-provisioning-failed",
			"Error",
			"Synchronization failed.",
			"CUST-0001",
			"PROJ-0001",
		)

		self.assertEqual(payload["type"], "message")
		self.assertEqual(len(payload["attachments"]), 1)
		attachment = payload["attachments"][0]
		self.assertEqual(attachment["contentType"], "application/vnd.microsoft.card.adaptive")
		self.assertIsNone(attachment["contentUrl"])
		self.assertEqual(attachment["content"]["type"], "AdaptiveCard")
		self.assertEqual(attachment["content"]["version"], "1.2")
		self.assertEqual(attachment["content"]["body"][0]["color"], "Attention")
		self.assertEqual(
			attachment["content"]["body"][2]["facts"],
			[
				{"title": "Source", "value": "customer-provisioning-failed"},
				{"title": "Customer", "value": "CUST-0001"},
				{"title": "Project", "value": "PROJ-0001"},
			],
		)

	def test_sales_order_project_name_preserves_customer_context(self):
		sales_order = types.SimpleNamespace(
			customer_name="Example GmbH", customer="CUST-0001", name="SO-0001"
		)
		self.assertEqual(_sales_order_project_name(sales_order), "Example GmbH — SO-0001")
