# Working Time migrations

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
