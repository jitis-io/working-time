from unittest import TestCase

import frappe

from working_time.install import insert_docs


class TestInstall(TestCase):
	def test_internal_project_type_is_provisioned_idempotently(self):
		if frappe.db.exists("Project Type", "Internal"):
			frappe.delete_doc("Project Type", "Internal", force=True)

		insert_docs()
		insert_docs()

		self.assertEqual(frappe.db.count("Project Type", {"project_type": "Internal"}), 1)
