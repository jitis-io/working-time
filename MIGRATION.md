# Working Time migrations

## 1.5.0 — native Work Cockpit

1. Promote the tested immutable ERP image; do not run `bench update` or pull an app branch in production.
2. Run the normal site migration and asset build. The migration idempotently adds the Issue/Task operational
   state, Issue planning date, Project Contract link and Task attachment display fields.
3. Confirm `/app/work-cockpit` as a System Manager and as one assigned Employee. The employee must not see
   an unassigned Issue or Task, even when its role could otherwise list that DocType.
4. Promote one Issue twice and confirm both actions route to the same open Task. Confirm private Issue files
   are linked from that Task without creating additional `File` records.
5. Compare **Nicht abgerechnet** with a narrow Billing Review preview. Eligible and exception states must
   agree; invoice submission remains manual.
6. Provider apps are optional and activated separately. A provider outage must leave native work visible.

## 1.3.1 — upgrade ordering hotfix

- Existing sites now create the v1.3 Project and integration custom fields before the data backfill patch queries them.
- Fresh installs and sites upgrading from 1.2.1 use the same migration path.

## 1.3.0 — unified Working Time and Helpdesk booking

1. Take and verify a database backup. Ensure Helpdesk 1.28.1 and Telephony are installed.
2. Run `bench --site <site> migrate`. The patch aborts before cleanup if a Project has conflicting native/legacy Sales Orders or if scripts/reports still reference the retired ALYF Task fields.
3. Run `bench build --app working_time` and `bench restart`.
4. Confirm all historical Working Time counts and submitted raw durations are unchanged. Check that no `Project-source_sales_order`, `Task-custom_is_active` or `Task-custom_hourly_billed` Custom Field remains.
5. Configure **Working Time Settings**, Employee user mappings, Project billing models, native Sales Orders and hourly rates.
6. Smoke-test: internal Helpdesk ticket → **Zeit buchen** → daily Working Time → complete allocation → submit → submitted Timesheet → Billing Review → draft Sales Invoice.
7. Verify a customer project mismatch, wrong Task, missing Employee mapping and customer-portal booking attempt are rejected.

## 1.2.0 — native ERPNext work and billing model

1. Back up the ERPNext site and verify that the backup can be read before deployment.
2. Verify **Employee > User ID** for every employee login. After this upgrade, non-System-Manager users
   without that mapping cannot list or open Working Time records or run either Working Time report.
3. Deploy the app and run:

   ```bash
   bench --site <site> migrate
   bench build --app working_time
   bench restart
   ```

4. Test with one employee login: its own record must be visible and another Employee's record must not be
   listed, opened or accepted by either report. Test an unmapped non-System-Manager login and confirm it is
   denied. System Managers remain unrestricted.
5. Verify that **Platform Operations** replaces the old integration workspace and contains only native project provisioning, billing review, alert and settings links.
6. Confirm that all retired external-integration DocTypes, custom fields, credentials and scheduled jobs are gone.
7. Verify new Sales Order project provisioning in a disposable example. It creates only the ERPNext Project.
8. Create a Billing Review for a narrow test period and verify the groups. Actual and raw billable hours are retained; only the daily customer/project/task aggregate is rounded upward to a quarter hour.
9. Create invoice drafts. This changes the review to **Draft Created** and does not submit or send anything. Review and submit each Sales Invoice manually, then choose **Finalize submitted invoices**.

The included post-model-sync patch changes legacy Billing Review rows from **Invoiced** to **Draft Created** when at least one linked Sales Invoice is not submitted. It does not rewrite historical Timesheet hours. Submitted historical time can only be corrected through ERPNext's cancellation/amendment workflow so the audit trail remains intact.
