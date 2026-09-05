"""Disposable native ERP workflow regressions; all fixtures are explicitly test-labelled."""

import json
import queue
import threading
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from working_time.issues import book_time, get_or_create_daily_working_time
from working_time.platform_operations import (
	create_billing_invoice_drafts,
	create_billing_review,
	create_project_time_invoice_draft,
)


class TestDailyWorkflow(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.suffix = uuid.uuid4().hex[:8]
		self.day = "2026-08-17"
		# A clean ERPNext install has not run its interactive setup wizard.
		# Supply the native master roots required by real Company/Invoice documents.
		for values in (
			{"doctype": "Gender", "name": "Male", "gender": "Male"},
			{"doctype": "Warehouse Type", "name": "Transit", "warehouse_type": "Transit"},
			{
				"doctype": "Customer Group",
				"name": "All Customer Groups",
				"customer_group_name": "All Customer Groups",
				"is_group": 1,
			},
			{
				"doctype": "Customer Group",
				"name": "_Test WT Customers",
				"customer_group_name": "_Test WT Customers",
				"parent_customer_group": "All Customer Groups",
				"is_group": 0,
			},
			{
				"doctype": "Territory",
				"name": "All Territories",
				"territory_name": "All Territories",
				"is_group": 1,
			},
			{
				"doctype": "Item Group",
				"name": "All Item Groups",
				"item_group_name": "All Item Groups",
				"is_group": 1,
			},
			{"doctype": "UOM", "name": "Hour", "uom_name": "Hour"},
			{"doctype": "Project Type", "name": "Internal", "project_type": "Internal"},
			{
				"doctype": "Price List",
				"name": "_Test WT Selling EUR",
				"price_list_name": "_Test WT Selling EUR",
				"currency": "EUR",
				"selling": 1,
				"enabled": 1,
			},
		):
			if not frappe.db.exists(values["doctype"], values["name"]):
				frappe.get_doc(values).insert()
		for year in {2026, frappe.utils.getdate().year}:
			if not frappe.db.exists("Fiscal Year", {"year_start_date": f"{year}-01-01"}):
				frappe.get_doc(
					{
						"doctype": "Fiscal Year",
						"year": str(year),
						"year_start_date": f"{year}-01-01",
						"year_end_date": f"{year}-12-31",
					}
				).insert()
		self.company = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": f"_Test WT {self.suffix}",
				"abbr": self.suffix,
				"default_currency": "EUR",
				"country": "Germany",
			}
		).insert()
		self.previous_default_company = frappe.db.get_single_value("Global Defaults", "default_company")
		frappe.db.set_single_value("Global Defaults", "default_company", self.company.name)
		self.employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": f"_Test WT {self.suffix}",
				"company": self.company.name,
				"date_of_joining": "2020-01-01",
				"date_of_birth": "1990-01-01",
				"gender": "Male",
				"status": "Active",
			}
		).insert()
		self.customers = []
		self.projects = []
		for label in ("A", "B"):
			customer = frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": f"_Test WT {label} {self.suffix}",
					"customer_group": "_Test WT Customers",
					"territory": "All Territories",
					"customer_type": "Company",
					"default_price_list": "_Test WT Selling EUR",
				}
			).insert()
			customer.reload()
			project = frappe.get_doc("Project", customer.customer_project)
			project.time_billable = 1
			project.billing_rate = 120
			project.save()
			self.customers.append(customer)
			self.projects.append(project)
		self.internal = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": f"_Test WT Internal {self.suffix}",
				"project_type": "Internal",
				"company": self.company.name,
			}
		).insert()
		self.issue = frappe.get_doc(
			{
				"doctype": "Issue",
				"subject": f"_Test WT Issue {self.suffix}",
				"customer": self.customers[0].name,
			}
		).insert()
		self.task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": f"_Test WT Task {self.suffix}",
				"issue": self.issue.name,
			}
		).insert()
		self.identity = patch("working_time.issues.get_user_employee", return_value=self.employee.name)
		self.identity.start()
		self.addCleanup(self.identity.stop)

	def book(self, project=None, minutes=30, **kwargs):
		return book_time(
			project=project or self.projects[0].name,
			date=self.day,
			duration_minutes=minutes,
			customer_description="_Test verified service",
			internal_note="_Test private note",
			billable=1,
			**kwargs,
		)

	def close(self, result, start="09:00:00", end="09:30:00", pause=0):
		doc = frappe.get_doc("Working Time", result["working_time"])
		doc.check_in, doc.check_out, doc.indicated_break = start, end, pause
		doc.save()
		doc.submit()
		return doc

	def test_two_customers_optional_work_items_break_and_repeated_close(self):
		real_project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": f"_Test WT Separate Project {self.suffix}",
				"customer": self.customers[0].name,
				"company": self.company.name,
				"time_billable": 0,
			}
		).insert()
		first = self.book(minutes=12, issue=self.issue.name, task=self.task.name)
		self.book(self.projects[1].name, minutes=18)
		self.book(self.internal.name, minutes=15)
		self.book(real_project.name, minutes=15)
		doc = self.close(first, end="10:15:00", pause=15 * 60)
		self.assertEqual(doc.unallocated_time, 0)
		self.assertEqual(doc.time_logs[2].billable, "0%")
		self.assertEqual(doc.time_logs[3].billable, "0%")
		self.assertEqual(frappe.db.count("Timesheet", {"working_time": doc.name, "docstatus": 1}), 4)
		self.assertEqual(frappe.db.count("Attendance", {"working_time": doc.name, "docstatus": 1}), 1)
		self.assertEqual(get_or_create_daily_working_time(self.employee.name, self.day).name, doc.name)
		doc.submit()
		self.assertEqual(frappe.db.count("Timesheet", {"working_time": doc.name, "docstatus": 1}), 4)
		with self.assertRaisesRegex(frappe.ValidationError, "already submitted"):
			self.book()
		self.assertEqual(frappe.db.count("Working Time", {"employee": self.employee.name, "docstatus": 1}), 1)

	def test_request_retry_saves_once_and_rejects_changed_payload(self):
		key = str(uuid.uuid4())
		first = self.book(booking_request_id=key)
		self.assertEqual(self.book(booking_request_id=key), first)
		self.assertEqual(len(frappe.get_doc("Working Time", first["working_time"]).time_logs), 1)
		with self.assertRaisesRegex(frappe.ValidationError, "already saved"):
			self.book(minutes=31, booking_request_id=key)
		doc = self.close(first)
		self.assertEqual(self.book(booking_request_id=key), first)
		self.assertEqual(len(doc.time_logs), 1)

	def test_parallel_booking_requests_share_one_day_without_lost_or_duplicate_rows(self):
		# These explicitly labelled fixtures are committed only in the disposable test site,
		# so each transaction sees the same employee and native project.
		self.addCleanup(self.cleanup_committed_fixtures)
		frappe.db.commit()
		site = frappe.local.site
		start = threading.Barrier(2)
		errors = queue.Queue()
		results = queue.Queue()
		conflicts = queue.Queue()
		key = str(uuid.uuid4())

		def request(request_id):
			try:
				frappe.init(site=site)
				frappe.connect()
				frappe.set_user("Administrator")
				start.wait(timeout=15)
				for attempt in range(3):
					try:
						result = self.book(booking_request_id=request_id)
						frappe.db.commit()
						results.put(result)
						break
					except frappe.QueryDeadlockError:
						# MariaDB snapshot isolation aborts a stale transaction. Model a
						# new HTTP request with the same UUID, never weaken isolation or
						# retry a write inside the failed transaction.
						frappe.db.rollback()
						conflicts.put(request_id)
						if attempt == 2:
							raise
			except BaseException as error:
				errors.put(error)
				frappe.db.rollback()
			finally:
				frappe.destroy()

		for keys, expected_count in (([key, key], 1), ([str(uuid.uuid4()), str(uuid.uuid4())], 3)):
			threads = [
				threading.Thread(target=request, args=(request_id,), daemon=True) for request_id in keys
			]
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join(30)
				self.assertFalse(thread.is_alive(), "Concurrent booking request did not finish")
			if not errors.empty():
				raise errors.get()
			frappe.db.rollback()
			name = results.get()["working_time"]
			self.assertEqual(results.get()["working_time"], name)
			self.assertEqual(len(frappe.get_doc("Working Time", name).time_logs), expected_count)
			self.assertEqual(frappe.db.count("Working Time", {"employee": self.employee.name}), 1)
		print(f"Concurrent booking transaction retries: {conflicts.qsize()}")

	def cleanup_committed_fixtures(self):
		"""Remove only this test's committed records after multi-connection assertions."""
		frappe.db.rollback()
		for name in frappe.get_all("Working Time", filters={"employee": self.employee.name}, pluck="name"):
			frappe.delete_doc("Working Time", name)
		frappe.delete_doc("Task", self.task.name)
		frappe.delete_doc("Issue", self.issue.name)
		for customer, project in zip(self.customers, self.projects, strict=True):
			frappe.db.set_value("Customer", customer.name, "customer_project", None)
			frappe.delete_doc("Project", project.name)
			frappe.delete_doc("Customer", customer.name)
		frappe.delete_doc("Project", self.internal.name)
		frappe.delete_doc("Employee", self.employee.name)
		frappe.db.set_single_value("Global Defaults", "default_company", self.previous_default_company)
		frappe.delete_doc("Company", self.company.name)
		frappe.db.commit()

	def test_server_rejects_cross_customer_and_wrong_task_project(self):
		with self.assertRaises(frappe.ValidationError):
			self.book(self.projects[1].name, issue=self.issue.name)
		with self.assertRaises(frappe.ValidationError):
			self.book(self.projects[1].name, task=self.task.name)
		self.issue.customer = self.customers[1].name
		with self.assertRaisesRegex(frappe.ValidationError, "same customer"):
			self.issue.save()
		self.projects[0].customer = self.customers[1].name
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be changed"):
			self.projects[0].save()

	def test_task_context_rejects_closed_project(self):
		self.internal.status = "Completed"
		self.internal.save()
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": f"_Test closed {self.suffix}",
				"project": self.internal.name,
			}
		).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "open project"):
			self.book(self.internal.name, task=task.name)

	def test_real_project_customer_change_cannot_reassign_existing_time(self):
		project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": f"_Test WT Ownership {self.suffix}",
				"customer": self.customers[0].name,
				"company": self.company.name,
			}
		).insert()
		self.book(project.name)
		project.customer = self.customers[1].name
		with self.assertRaisesRegex(frappe.ValidationError, "after work or billing records"):
			project.save()
		self.assertEqual(frappe.db.get_value("Project", project.name, "customer"), self.customers[0].name)

	def test_draft_edit_and_unallocated_time_block_submission(self):
		result = self.book()
		doc = frappe.get_doc("Working Time", result["working_time"])
		doc.time_logs[0].duration = 20 * 60
		doc.save()
		self.assertEqual(doc.working_time, 20 * 60)
		doc.check_in, doc.check_out = "09:00:00", "09:30:00"
		with self.assertRaisesRegex(frappe.ValidationError, "complete net working time"):
			doc.submit()

	def test_missing_project_cannot_create_a_booked_or_submitted_day(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Select a project"):
			book_time(project="", date=self.day, duration_minutes=30)
		doc = frappe.get_doc(
			{
				"doctype": "Working Time",
				"employee": self.employee.name,
				"date": self.day,
				"check_in": "09:00:00",
				"check_out": "09:30:00",
				"time_logs": [{"duration": 30 * 60, "customer_description": "_Test unallocated"}],
			}
		).insert()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()

	def test_unbilled_cancel_amend_preserves_history_and_recreates_dependencies_once(self):
		from frappe.desk.form.linked_with import cancel_all_linked_docs, get_submitted_linked_docs

		doc = self.close(self.book(booking_request_id=str(uuid.uuid4())))
		# Native Desk cancellation first cancels linked submitted documents.
		linked = get_submitted_linked_docs("Working Time", doc.name)
		self.assertEqual({row["doctype"] for row in linked["docs"]}, {"Attendance", "Timesheet"})
		cancel_all_linked_docs(json.dumps(linked["docs"]))
		doc.cancel()
		self.assertEqual(frappe.db.count("Timesheet", {"working_time": doc.name, "docstatus": 1}), 0)
		amended = frappe.copy_doc(doc)
		amended.amended_from = doc.name
		amended.docstatus = 0
		amended.time_logs[0].duration = 20 * 60
		amended.check_out = "09:20:00"
		amended.insert()
		self.assertFalse(amended.time_logs[0].booking_request_id)
		amended.submit()
		self.assertEqual(frappe.db.count("Timesheet", {"working_time": amended.name, "docstatus": 1}), 1)
		self.assertEqual(frappe.db.count("Attendance", {"working_time": amended.name, "docstatus": 1}), 1)
		self.assertEqual(frappe.db.get_value("Working Time", doc.name, "docstatus"), 2)

	def test_native_multi_customer_timesheet_creates_invoice_drafts_without_submitting(self):
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": f"_Test WT Native Hour {self.suffix}",
				"item_group": "All Item Groups",
				"stock_uom": "Hour",
				"is_stock_item": 0,
			}
		).insert()
		frappe.db.set_single_value("Working Time Settings", "default_time_billing_item", item.name)
		timesheet = frappe.get_doc(
			{
				"doctype": "Timesheet",
				"company": self.company.name,
				"employee": self.employee.name,
				"time_logs": [
					{
						"activity_type": "Default",
						"from_time": f"{self.day} 18:00:00",
						"to_time": f"{self.day} 18:12:00",
						"project": self.projects[0].name,
						"is_billable": 1,
						"customer_description": "Native customer service A",
						"billing_rate": 120,
						"internal_note": "Private native note A",
					},
					{
						"activity_type": "Default",
						"from_time": f"{self.day} 18:30:00",
						"to_time": f"{self.day} 18:48:00",
						"project": self.projects[1].name,
						"is_billable": 1,
						"customer_description": "Native customer service B",
						"billing_rate": 120,
						"internal_note": "Private native note B",
					},
				],
			}
		).insert()
		self.assertFalse(timesheet.get("customer"))
		self.assertFalse(timesheet.get("parent_project"))
		self.assertFalse(timesheet.get("working_time"))
		timesheet.submit()

		preview = create_billing_review(self.day, self.day)
		self.assertEqual(preview["eligible_group_count"], 2)
		review = frappe.get_doc("Billing Review", preview["name"])
		self.assertFalse(review.project)
		self.assertEqual(review.status, "Preview")
		rows = {row.customer: row for row in review.items if row.status == "Eligible"}
		self.assertEqual(set(rows), {customer.name for customer in self.customers})
		self.assertEqual(frappe.utils.flt(rows[self.customers[0].name].hours, 2), 0.25)
		self.assertEqual(frappe.utils.flt(rows[self.customers[1].name].hours, 2), 0.5)

		drafted = create_billing_invoice_drafts(review.name)
		self.assertTrue(drafted["created"])
		self.assertEqual(len(drafted["sales_invoices"]), 2)
		invoices = [frappe.get_doc("Sales Invoice", name) for name in drafted["sales_invoices"]]
		self.assertEqual({invoice.customer for invoice in invoices}, {c.name for c in self.customers})
		self.assertTrue(all(invoice.docstatus == 0 for invoice in invoices))
		self.assertTrue(all(len(invoice.timesheets) == 1 for invoice in invoices))
		descriptions = "\n".join(row.description for invoice in invoices for row in invoice.items)
		self.assertIn("Native customer service A", descriptions)
		self.assertIn("Native customer service B", descriptions)
		self.assertNotIn("Private native note", descriptions)
		self.assertEqual(frappe.db.get_value("Billing Review", review.name, "status"), "Draft Created")

	def test_submitted_rate_survives_project_change_and_missing_rate_is_an_exception(self):
		from working_time.platform_operations import _lock_billing_sources, _review_source_items

		doc = self.close(self.book())
		self.projects[0].reload()
		self.projects[0].billing_rate = 139
		self.projects[0].save()
		preview = create_billing_review(self.day, self.day, project=self.projects[0].name)
		review = frappe.get_doc("Billing Review", preview["name"])
		self.assertEqual(preview["eligible_group_count"], 1)
		self.assertEqual(review.items[0].rate, 120)
		source_name = review.items[0].timesheet_detail
		self.assertEqual(frappe.db.get_value("Timesheet Detail", source_name, "base_billing_rate"), 120)
		self.assertEqual(frappe.db.count("Timesheet", {"working_time": doc.name, "docstatus": 1}), 1)
		frappe.db.set_value("Timesheet Detail", source_name, "base_billing_rate", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "changed after the preview"):
			_lock_billing_sources(_review_source_items(review.items))
		missing = create_billing_review(self.day, self.day, project=self.projects[0].name)
		self.assertEqual(missing["eligible_group_count"], 0)
		self.assertEqual(missing["counts"], {"Missing Rate": 1})
		missing_review = frappe.get_doc("Billing Review", missing["name"])
		self.assertEqual(missing_review.items[0].rate, 0)
		self.assertEqual(missing_review.items[0].amount, 0)

	def test_billing_draft_rounds_after_aggregation_and_repeat_does_not_duplicate(self):
		from frappe.desk.form.linked_with import cancel_all_linked_docs, get_submitted_linked_docs

		result = self.book(minutes=7)
		self.book(minutes=7)
		doc = self.close(result, end="09:14:00")
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": f"_Test WT Hour {self.suffix}",
				"item_group": "All Item Groups",
				"stock_uom": "Hour",
				"is_stock_item": 0,
			}
		).insert()
		frappe.db.set_single_value("Working Time Settings", "default_time_billing_item", item.name)
		drafted = create_project_time_invoice_draft(self.projects[0].name, self.day, self.day)
		invoice = frappe.get_doc("Sales Invoice", drafted["sales_invoices"][0])
		self.assertEqual(invoice.docstatus, 0)
		self.assertEqual(invoice.items[0].qty, 0.25)
		self.assertEqual(len(invoice.timesheets), 2)
		self.assertTrue(all("private note" not in row.description for row in invoice.timesheets))
		self.assertFalse(create_billing_invoice_drafts(drafted["review"])["created"])
		frappe.db.savepoint("cancel_claimed_day")
		with self.assertRaisesRegex(frappe.ValidationError, "billing already references"):
			doc.cancel()
		frappe.db.rollback(save_point="cancel_claimed_day")
		doc.reload()
		with self.assertRaisesRegex(frappe.ValidationError, "no eligible rows"):
			create_project_time_invoice_draft(self.projects[0].name, self.day, self.day)
		self.assertEqual(frappe.db.count("Sales Invoice", {"customer": self.customers[0].name}), 1)
		# Deliberate submission ONLY of this isolated, labelled test invoice.
		invoice.submit()
		self.assertEqual(frappe.db.get_value("Billing Review", drafted["review"], "status"), "Invoiced")
		self.assertEqual(frappe.db.get_value("Working Time", doc.name, "docstatus"), 1)
		frappe.db.savepoint("cancel_invoiced_day")
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()
		frappe.db.rollback(save_point="cancel_invoiced_day")
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 1)
		linked = get_submitted_linked_docs("Working Time", doc.name)
		frappe.db.savepoint("cancel_invoiced_linked")
		with self.assertRaises(frappe.ValidationError):
			cancel_all_linked_docs(json.dumps(linked["docs"]))
			doc.cancel()
		frappe.db.rollback(save_point="cancel_invoiced_linked")
		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 1)

	def test_nonbillable_time_never_becomes_eligible(self):
		self.projects[0].time_billable = 0
		self.projects[0].save()
		doc = self.close(self.book())
		self.assertEqual(doc.time_logs[0].billable, "0%")
		result = create_billing_review(self.day, self.day, self.projects[0].name)
		self.assertFalse(frappe.get_doc("Billing Review", result["name"]).items)

	def test_preview_references_block_native_linked_cancellation(self):
		from frappe.desk.form.linked_with import cancel_all_linked_docs, get_submitted_linked_docs

		doc = self.close(self.book())
		create_billing_review(self.day, self.day, self.projects[0].name)
		linked = get_submitted_linked_docs("Working Time", doc.name)
		frappe.db.savepoint("cancel_preview_day")
		with self.assertRaises(frappe.ValidationError):
			cancel_all_linked_docs(json.dumps(linked["docs"]))
			doc.cancel()
		frappe.db.rollback(save_point="cancel_preview_day")
		self.assertEqual(frappe.db.get_value("Working Time", doc.name, "docstatus"), 1)
		self.assertEqual(frappe.db.count("Timesheet", {"working_time": doc.name, "docstatus": 1}), 1)
