from unittest import TestCase
from unittest.mock import call, patch

import frappe

from working_time.install import ensure_work_cockpit_metadata, insert_docs


class TestInstall(TestCase):
	def test_internal_project_type_is_provisioned_idempotently(self):
		if frappe.db.exists("Project Type", "Internal"):
			frappe.delete_doc("Project Type", "Internal", force=True)

		insert_docs()
		insert_docs()

		self.assertEqual(frappe.db.count("Project Type", {"project_type": "Internal"}), 1)

	def test_work_cockpit_metadata_is_force_synced_idempotently(self):
		with patch("working_time.install.frappe.reload_doc") as reload_doc:
			ensure_work_cockpit_metadata()
			ensure_work_cockpit_metadata()

		self.assertEqual(
			reload_doc.call_args_list,
			[
				call("working_time", "page", "work_cockpit", force=True),
				call("working_time", "workspace", "platform_operations", force=True),
				call("working_time", "page", "work_cockpit", force=True),
				call("working_time", "workspace", "platform_operations", force=True),
			],
		)
