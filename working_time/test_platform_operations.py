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
	_provisioning_preview,
	_round_billable_hours,
	_sales_order_project_name,
	_teams_adaptive_card,
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
			FakeDocument(name="SO-0001", customer="CUST-0001", customer_name="Example GmbH")
		)

		self.assertEqual(
			preview,
			{
				"sales_order": "SO-0001",
				"customer": "CUST-0001",
				"erpnext_project": "Example GmbH — SO-0001",
			},
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
				},
				{
					**base,
					"timesheet": "TS-0002",
					"timesheet_detail": "ROW-0002",
					"actual_hours": "0.10",
					"raw_billable_hours": "0.10",
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
		sales_order = FakeDocument(name="SO-0001", company="JITIS", currency="EUR")
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
		self.assertEqual(review.status, "Draft Created")
		self.assertEqual(item.status, "Draft Created")
		self.assertEqual(item.sales_invoice, "SINV-0001")
		self.assertEqual(invoice.values["items"][0]["qty"], 0.25)

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
