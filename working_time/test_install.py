from unittest import TestCase
from unittest.mock import call, patch

import frappe
from frappe.translate import get_translations_from_apps

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

	def test_jitis_work_navigation_keeps_the_stable_v16_route_and_compiled_branding(self):
		# Reproduce the 1.6.0 database state: Frappe already normalized label to
		# the document name, while the incompatible translated title remained.
		frappe.db.set_value("Workspace", "Platform Operations", "title", "JITIS Work")

		try:
			ensure_work_cockpit_metadata()
			ensure_work_cockpit_metadata()

			workspace = frappe.get_doc("Workspace", "Platform Operations")
			self.assertEqual(workspace.label, "Platform Operations")
			self.assertEqual(workspace.title, "Platform Operations")
			self.assertEqual(frappe.db.count("Workspace", {"name": "Platform Operations"}), 1)

			self.assertEqual(frappe.db.count("Workspace Sidebar", {"name": "Platform Operations"}), 1)
			self.assertEqual(
				frappe.db.count(
					"Workspace Sidebar Item",
					{
						"parent": "Platform Operations",
						"label": "Home",
						"link_to": "Platform Operations",
						"link_type": "Workspace",
					},
				),
				1,
			)
			self.assertEqual(frappe.db.count("Desktop Icon", {"name": "Platform Operations"}), 1)
			self.assertEqual(
				frappe.db.get_value(
					"Desktop Icon",
					"Platform Operations",
					["label", "link_to", "link_type"],
				),
				("Platform Operations", "Platform Operations", "Workspace Sidebar"),
			)

			self.assertEqual(
				get_translations_from_apps("de", apps=["working_time"])["Platform Operations"],
				"JITIS Work",
			)
			self.assertEqual(
				get_translations_from_apps("en", apps=["working_time"])["Platform Operations"],
				"JITIS Work",
			)
		finally:
			ensure_work_cockpit_metadata()
