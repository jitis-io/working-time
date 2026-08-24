# Migration and acceptance checklist

## 1.8.0 customer-safe invoice evidence

- Run the normal site migration and confirm `Sales Invoice Timesheet.working_time_customer_snapshot` exists.
- Create a draft from Billing Review and verify every generated child row has the snapshot marker, a blank
  Activity Type and a customer-safe description made only from date, ticket reference and customer text.
- Render one invoice containing a native/unmarked row and confirm its description is not printed.
- Verify a customer, company or Project mismatch on the referenced Sales Order aborts before invoice creation.
- Verify mutating Working Time methods reject GET and the daily scheduler creates no blank draft by default.

## 1.7.3 billing-review consistency

- Run the normal site migration to reconcile existing Billing Reviews with their linked Sales Invoices.
- Create two previews for the same eligible Timesheet Detail and confirm that only the first can create a
  draft; the second must report the existing claim.
- Confirm the generated draft contains the exact native Sales Invoice Timesheet rows from the preview.
- Submit the draft and verify the Billing Review and its linked rows become `Invoiced` automatically.
- Cancel a linked invoice and verify the Billing Review becomes `Failed` while the source remains claimed.

## 1.7.2 customer-account stabilization

- Open Tasks linked to an Issue inherit that Issue's Project when the assignment is customer-safe.
- Existing open, non-template Issue Tasks without a Project are backfilled during migration.
- Reactivated Customers immediately receive or reopen their permanent customer Project.
- Purchase and Sales Invoice item forms use ERPNext's native grid lifecycle again; the Project is still
  copied server-side from the invoice header into empty item rows.
- Dead Teams alert runtime code and empty provisioning Python stubs are retired without deleting
  historical Platform Alert records.

## 1.7.1 customer-account layout correction

This patch gives the Customer Account tab its own sections so no custom field can inherit a column from
ERPNext's Costing tab. The monthly overview is full-width, duplicate context is removed, actions and KPIs
are grouped responsively, and server errors are converted to safe plain text before display. Canonical
customer-account Projects now show a concise translated message before Frappe's generic link error when
someone tries to close, deactivate or delete them. There is no business-data migration in this patch.

## 1.7.0 project-centred workflow

Deploy only through the immutable ERP platform release. The normal `bench --site <site> migrate` step
performs the idempotent metadata and customer-project migration.

Before release:

1. Run quality and clean-bench integration checks from `AGENTS.md`.
2. Confirm the production backup gate is enabled in the platform workflow.
3. Record counts for Customer, Project, open Issue, Working Time and Billing Review.

After migration:

1. `Platform Operations`, `Time Tracking`, `work-cockpit` and `working-time-quick-entry` are absent.
2. Every non-disabled Customer has `customer_project` set.
   On the 2026-08-20 production migration this meant 18 processed, 12 created and 6 existing Projects
   reused. Three case-only visible-name variants were corrected manually after the migration.
3. Every linked customer Project belongs to the same Customer, is open, and has the customer number as
   its visible project name. It uses manual progress so completed Tasks do not close the account.
4. Historical job Projects remain unchanged; no Projects are merged or deleted.
   The verified JITIS mismatch `P-2510-0001.project_name` is corrected from `K-2601013` to its linked
   Customer `K-2601008`; the Project record and every existing document link remain unchanged.
5. Open customer Issues that previously had no Project point to the canonical customer Project.
6. Existing non-default Issue or Task operational-state values still exist in hidden compatibility fields.
7. The time-billing Item previously stored in Platform Operations Settings is present in Working Time
   Settings.

Functional acceptance:

1. Open a customer Project and verify the **Customer Account** tab at desktop and narrow widths.
2. Book time from Project, Issue and Task. Each action must append exactly one row to the same daily
   Working Time draft and preserve Project, Issue/Task and descriptions.
3. Complete day close with start, end and break; submit once and verify Attendance plus Timesheet links.
4. Create a Purchase Invoice from the Project, add an item and verify its Project. After submit, the month
   view must include the base net amount; a draft must not count as actual cost.
5. From the Project month view confirm **Create time invoice draft**. It must include only eligible time for
   that Project and month, open exactly one Sales Invoice draft, and never submit or email it.
6. Submit a reviewed Sales Invoice and verify the month view separates draft and submitted revenue.
7. Verify users without Timesheet, Purchase Invoice or Sales Invoice read permission receive no protected
   rows or amounts.

Rollback is forward-only: do not downgrade the database, pull mutable branches or run `bench update` on
the VM. Correct defects in a new app tag and platform image, or use the documented production restore
procedure for a declared migration incident.
