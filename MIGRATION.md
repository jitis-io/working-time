# Migration and acceptance checklist

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
   On the 2026-08-20 production preflight this means 18 processed, 15 created and 3 exact Projects reused
   and reopened.
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
