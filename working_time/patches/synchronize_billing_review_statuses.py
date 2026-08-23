import frappe

from working_time.platform_operations import _synchronize_billing_review_status


def execute():
	"""Reconcile historical reviews that already link generated invoices."""
	if not frappe.db.exists("DocType", "Billing Review"):
		return
	for review_name in frappe.get_all(
		"Billing Review",
		pluck="name",
	):
		review = frappe.get_doc("Billing Review", review_name)
		if any(item.sales_invoice for item in review.items):
			_synchronize_billing_review_status(review)
