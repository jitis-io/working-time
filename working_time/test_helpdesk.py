import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from working_time.helpdesk import validate_ticket_booking


class TestHelpdeskBooking(unittest.TestCase):
	def test_direct_working_time_booking_requires_ticket_read_permission(self):
		ticket = SimpleNamespace(
			name="HD-TICKET-0001",
			customer=None,
			meta=SimpleNamespace(has_field=lambda fieldname: False),
			get=lambda fieldname, default=None: default,
		)

		with (
			patch("working_time.helpdesk.require_time_booking_identity", return_value="Administrator"),
			patch("working_time.helpdesk._target_ticket", return_value=ticket.name),
			patch("working_time.helpdesk.frappe.get_doc", return_value=ticket),
			patch("working_time.helpdesk.frappe.has_permission", return_value=False),
			self.assertRaises(frappe.PermissionError),
		):
			validate_ticket_booking(ticket.name, "PROJ-0001")

	def test_ticket_time_can_be_captured_before_project_allocation(self):
		ticket = SimpleNamespace(
			name="HD-TICKET-0002",
			customer=None,
			meta=SimpleNamespace(has_field=lambda fieldname: False),
			get=lambda fieldname, default=None: default,
		)

		with (
			patch("working_time.helpdesk.require_time_booking_identity", return_value="Administrator"),
			patch("working_time.helpdesk._target_ticket", return_value=ticket.name),
			patch("working_time.helpdesk.frappe.get_doc", return_value=ticket),
			patch("working_time.helpdesk.frappe.has_permission", return_value=True),
		):
			validate_ticket_booking(ticket.name, None)
