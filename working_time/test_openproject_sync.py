import sys
import types
import unittest
from unittest.mock import patch


def _bootstrap_frappe_stub() -> None:
	if "frappe" in sys.modules:
		return

	def throw(message):
		raise RuntimeError(message)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda message: message
	frappe.throw = throw
	frappe.db = types.SimpleNamespace(get_value=lambda *args, **kwargs: None)
	frappe.get_all = lambda *args, **kwargs: []
	frappe.get_doc = lambda *args, **kwargs: None
	frappe.enqueue = lambda *args, **kwargs: None
	frappe.whitelist = lambda *args, **kwargs: (lambda fn: fn)
	sys.modules["frappe"] = frappe


_bootstrap_frappe_stub()

from working_time.openproject_sync import _project_customer


class TestOpenProjectSync(unittest.TestCase):
	def test_project_customer_uses_project_identifier(self):
		project_payload = {"identifier": "K-2601002", "name": "K-2601002"}

		with patch("working_time.openproject_sync._customer_name_by_identifier") as lookup:
			lookup.side_effect = lambda value: value if value == "K-2601002" else None

			self.assertEqual(_project_customer(project_payload), "K-2601002")

		lookup.assert_called_once_with("K-2601002")

	def test_project_customer_uses_parent_project_identifier_for_subprojects(self):
		project_payload = {
			"identifier": "arbeitspaket-4",
			"name": "Arbeitspaket 4",
			"_embedded": {
				"parent": {
					"identifier": "k-2601002",
					"name": "K-2601002",
				}
			},
			"_links": {
				"parent": {
					"href": "/api/v3/projects/9",
					"title": "K-2601002",
				}
			},
		}

		calls = []

		def lookup(value):
			calls.append(value)
			return "K-2601002" if value in {"k-2601002", "K-2601002"} else None

		with patch("working_time.openproject_sync._customer_name_by_identifier", side_effect=lookup):
			self.assertEqual(_project_customer(project_payload), "K-2601002")

		self.assertEqual(calls, ["arbeitspaket-4", "Arbeitspaket 4", "k-2601002"])

	def test_project_customer_ignores_non_project_parent(self):
		project_payload = {
			"identifier": "arbeitspaket-4",
			"name": "Arbeitspaket 4",
			"_links": {
				"parent": {
					"href": "/api/v3/portfolios/36",
					"title": "02-Kunden",
				}
			},
		}

		calls = []

		with patch(
			"working_time.openproject_sync._customer_name_by_identifier",
			side_effect=lambda value: calls.append(value) or None,
		):
			self.assertIsNone(_project_customer(project_payload))

		self.assertEqual(calls, ["arbeitspaket-4", "Arbeitspaket 4"])