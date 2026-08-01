# Working Time migrations

## 1.1.0 — forward-only ERPNext work and billing model

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
5. If OpenProject contains the last authoritative records, open **OpenProject Site** as a System Manager and deliberately queue the required one-time reconciliation types. Inspect every run in **Integration Control Center**. There are no automatic reconciliation schedules in 1.1.0.
6. Leave the OpenProject Site record available read-only until the import evidence and record counts have been accepted. A webhook is accepted only when its signature secret is configured; a pull-only final import does not need a webhook.
7. Verify new Sales Order project provisioning in a disposable example. Version 1.1.0 creates only the ERPNext Project and never creates a new OpenProject project.
8. Create a Billing Review for a narrow test period and verify the groups. Actual and raw billable hours are retained; only the daily customer/project/task aggregate is rounded upward to a quarter hour.
9. Create invoice drafts. This changes the review to **Draft Created** and does not submit or send anything. Review and submit each Sales Invoice manually, then choose **Finalize submitted invoices**.

The included post-model-sync patch changes legacy Billing Review rows from **Invoiced** to **Draft Created** when at least one linked Sales Invoice is not submitted. It does not rewrite historical Timesheet hours. Submitted historical time can only be corrected through ERPNext's cancellation/amendment workflow so the audit trail remains intact.
