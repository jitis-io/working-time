import json
import queue
import threading
import time
import uuid

import frappe
from frappe.tests import IntegrationTestCase

from working_time.platform_operations import _claimed_billing_sources, _lock_billing_sources


class TestBillingConcurrency(IntegrationTestCase):
	def test_source_lock_serializes_parallel_reviews_and_refreshes_claims(self):
		suffix = uuid.uuid4().hex[:12]
		source_name = f"TSD-{suffix}"
		winning_review = f"BR-WIN-{suffix}"
		losing_review = f"BR-LOSE-{suffix}"
		project = f"PROJ-{suffix}"
		site = frappe.local.site
		owner_locked = threading.Event()
		contender_started = threading.Event()
		contender_acquired = threading.Event()
		release_owner = threading.Event()
		errors: queue.Queue[BaseException] = queue.Queue()
		result: dict[str, object] = {}

		frappe.db.sql(
			"""
			insert into `tabTimesheet Detail`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			parent, parentfield, parenttype, project, is_billable, billing_hours,
			from_time, to_time, description, project_name, base_billing_rate)
			values (%s, now(), now(), 'Administrator', 'Administrator', 1, 1,
			%s, 'time_logs', 'Timesheet', %s, 1, 0.2,
			'2026-08-01 09:00:00', '2026-08-01 09:12:00', 'Concurrency test', %s, 120)
			""",
			(source_name, f"TS-{suffix}", project, project),
		)
		frappe.db.commit()

		def connect() -> None:
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user("Administrator")

		def winning_transaction() -> None:
			try:
				connect()
				frappe.db.sql(
					"select name from `tabTimesheet Detail` where name=%s for update",
					(source_name,),
				)
				owner_locked.set()
				if not release_owner.wait(10):
					raise TimeoutError("Timed out while holding the billing source lock")
				frappe.db.sql(
					"""
					insert into `tabBilling Review Item`
					(name, creation, modified, modified_by, owner, docstatus, idx,
					parent, parentfield, parenttype, timesheet_detail, source_count,
					source_details_json, status)
					values (%s, now(), now(), 'Administrator', 'Administrator', 0, 1,
					%s, 'items', 'Billing Review', %s, 1, %s, 'Draft Created')
					""",
					(
						f"BRI-WIN-{suffix}",
						winning_review,
						source_name,
						json.dumps([{"timesheet_detail": source_name}]),
					),
				)
				frappe.db.commit()
			except BaseException as exc:
				errors.put(exc)
				frappe.db.rollback()
			finally:
				frappe.destroy()

		def losing_transaction() -> None:
			try:
				connect()
				contender_started.set()
				locked = _lock_billing_sources(
					{
						source_name: frappe._dict(
							project=project,
							timesheet_detail=source_name,
							source_count=1,
							source_details_json="",
							raw_billable_hours=0.2,
							rate=120,
						)
					}
				)
				contender_acquired.set()
				result["locked"] = sorted(locked)
				result["claims"] = _claimed_billing_sources(
					exclude_review=losing_review,
					for_update=True,
				)
				frappe.db.rollback()
			except BaseException as exc:
				errors.put(exc)
				frappe.db.rollback()
			finally:
				frappe.destroy()

		winner = threading.Thread(target=winning_transaction, daemon=True)
		loser = threading.Thread(target=losing_transaction, daemon=True)
		try:
			winner.start()
			self.assertTrue(owner_locked.wait(10), "Winning transaction did not acquire the source lock")
			loser.start()
			self.assertTrue(contender_started.wait(10), "Losing transaction did not start")
			time.sleep(0.2)
			self.assertFalse(
				contender_acquired.is_set(),
				"Parallel review acquired the same Timesheet Detail before the winner committed",
			)
			release_owner.set()
			winner.join(10)
			loser.join(10)
			self.assertFalse(winner.is_alive(), "Winning billing transaction did not finish")
			self.assertFalse(loser.is_alive(), "Losing billing transaction did not finish")
			if not errors.empty():
				raise errors.get()
			self.assertEqual(result["locked"], [source_name])
			self.assertEqual(result["claims"], {source_name: "Draft Created"})
		finally:
			release_owner.set()
			winner.join(1)
			loser.join(1)
			frappe.db.sql(
				"delete from `tabBilling Review Item` where name=%s",
				(f"BRI-WIN-{suffix}",),
			)
			frappe.db.sql("delete from `tabTimesheet Detail` where name=%s", (source_name,))
			frappe.db.commit()
