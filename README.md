# Working Time

Project-centred time capture and billing preparation for ERPNext v16.

The technical app and Python package remain named `working_time` for upgrade compatibility. The app
does not provide a second workplace or project-management model. ERPNext **Project** is the visible
customer account and the single entry point for tickets, tasks, time, purchases and billing.

## Operating model

```text
Customer -> permanent customer Project -> Issue or Task -> ERPNext Timesheet
                                      -> Purchase Invoice costs
                                      -> monthly Billing Review
                                      -> reviewed Sales Invoice draft
```

- Every active Customer has one permanent customer Project. Its visible project name is the ERPNext
  customer number. Historical job Projects remain untouched and are not merged automatically.
- An Issue is incoming work. A Task is only needed for planned or multi-step work.
- ERPNext **Timesheet** is the primary time-entry record. Create one daily draft per employee and add
  one row for each customer Project. When a day spans multiple customers, leave the Timesheet header's
  Customer and Project empty and assign the Project on every time row.
- **Customer Description** on a Timesheet row is reviewed customer-facing text that can be copied to a
  later invoice draft. **Internal Note** stays internal and is never copied to customer output.
- **Book time** and **Day close** remain an optional compatibility path for the legacy Working Time
  workflow. Submitting a Working Time record creates native Timesheets and Attendance. Do not mix both
  entry paths for the same work, employee and day.
- Purchase Invoice rows carry the customer Project. ERPNext and the Project month view then show the
  net cost in company currency.
- In the **Billing Review** list, **Prepare month** collects all eligible submitted Timesheet rows for
  the selected period and all customer Projects. Review that preview before creating Sales Invoice
  drafts. Neither action submits or sends an invoice. Project-level invoice actions remain available
  for a deliberately narrower review.
- Purchase costs are visible in the month view but are not copied into a customer invoice automatically;
  sales item, markup and tax treatment require an explicit commercial decision.

## Project customer-account tab

Open an ERPNext Project and select **Customer Account**. The tab contains:

- a month selector;
- booked, billable and still-unbilled hours;
- internal time cost and billable value;
- submitted Purchase Invoice cost;
- draft and submitted Sales Invoice value;
- a compact list of time, purchase and sales entries;
- direct actions for time, day close, Issue, Task, Purchase Invoice, Sales Invoice and the confirmed time
  invoice draft.

ERPNext's native **Costing** and **Connections** tabs remain available for lifetime totals and complete
drill-down lists.

## Setup

1. Install the app and run the normal site migration.
2. Link every ERPNext Employee to its User ID.
3. Configure the hourly billing Item in **Working Time Settings**.
4. On a customer Project enable **Bill Time** and enter the verified hourly rate when hours are chargeable.
5. Maintain Activity Cost for each Employee when internal time cost is required.

The app keeps ERPNext's native records and permissions. Users without read access to Timesheets,
Purchase Invoices or Sales Invoices do not receive those details from the Project month API.

## Upgrade to 1.8.4

- Native ERPNext Timesheet drafts now expose editable **Customer Description** and **Internal Note**
  fields on every time row.
- The Billing Review list provides **Prepare month**. It creates one review across every eligible
  customer Project for the selected period; invoice drafts still require a separate reviewed action.
- ERPNext Timesheet is now the documented primary entry path. Working Time remains available as an
  optional compatibility workflow and is not a second billing source.

## Upgrade to 1.8.3

- Reopening **Daily close** returns the existing active day, including an already submitted day.
  Adding more time after submission is rejected; correct the day through reviewed Cancel/Amend.
- The booking dialog sends a stable `booking_request_id` UUID. Retrying the same request after a lost
  response returns the original Working Time instead of adding another row. A changed payload with
  the same key is rejected. API callers may opt into the same backward-compatible parameter.
- Booking requests are serialized per Employee, including the first daily draft creation. Independent
  bookings from two tabs are retained after successful requests, while an identical retry is applied
  once. MariaDB snapshot isolation can abort an overlapping request; retry in the same dialog with
  the same UUID. There is no automatic server rollback/retry of a caller's surrounding transaction.
- Issue and Task entry points enforce the same open-Project requirement as direct Project booking.
- Direct Working Time rows enforce the same Project and Task read permissions as the booking API.
- A permanent customer account cannot be reassigned to a different Customer or made customerless.
  Other Projects also keep their customer once work or billing records reference them.
- Referenced billing sources also block native Timesheet cancellation and Desk's linked-document
  cancellation path, before it can bypass the parent Working Time guard.
- The billing-source change guard compares hours at the Billing Review field's persisted precision,
  using Frappe's rounding policy. Native fractional-minute hours no longer produce a false drift
  error, while changes at the stored precision still block draft creation or submission.

Migration only adds two hidden, non-copyable booking metadata fields to Working Time Log. It does not
change historical time, billing rates or billing eligibility. A newly opened dialog is a new booking;
after reloading the page, inspect the daily draft before re-entering work with an uncertain outcome.

## Upgrade to 1.8.2

Version 1.8.2 makes the duration-first workflow more direct without changing any billing or
submission behavior:

- **Book time** can optionally open the exact daily Working Time record returned by the server;
- existing post-booking callbacks still run before navigation;
- a failure to start navigation is reported separately and never misrepresents the already saved
  time as a failed booking.

## Upgrade to 1.8.1

Version 1.8.1 tightens the simplified Project-centred workflow and the customer invoice boundary:

- mutating HTTP methods are explicitly POST-only;
- daily blank drafts are opt-in and duplicate reminder paths are removed;
- Sales Order customer, company and Project relationships are revalidated before invoice creation;
- invoice evidence freezes only the reviewed customer description and ticket reference;
- an internal Activity Type is never copied to customer output;
- every new Working-Time invoice row carries a hidden customer-snapshot marker so the print format can
  suppress untrusted descriptions on native or historical rows.

## Upgrade to 1.7.3

Version 1.7.3 makes the reviewed time-billing handoff concurrency-safe and keeps its state aligned with
ERPNext's native Sales Invoice and Timesheet links:

- draft creation locks and revalidates the exact Timesheet Detail rows before it creates an invoice;
- the generated Sales Invoice carries those native Timesheet references and rejects removed, duplicated or
  already billed sources before submit;
- submitting or cancelling a linked Sales Invoice synchronizes the Billing Review automatically;
- cancelled or missing invoices remain claimed and are surfaced as failed instead of silently becoming
  billable again;
- an idempotent migration reconciles historical Billing Reviews that already contain invoice links.

## Upgrade to 1.7.2

Version 1.7.2 stabilizes the customer-account flow without adding another work surface:

- an open Task linked to an Issue inherits the Issue's customer Project, while conflicting customer or
  Project combinations are rejected;
- the migration fills that Project only on safe open, non-template Tasks that still have no Project;
- reactivating an existing Customer immediately restores its permanent customer Project;
- invoice item forms keep ERPNext's native grid lifecycle, preventing the white frozen detail view and
  restoring the standard keyboard order;
- unused Teams alert runtime code and the final empty provisioning class stubs are removed, while
  historical Platform Alert records remain untouched.

## Upgrade to 1.7.0

Version 1.7.0 removes the parallel JITIS Work / My Work user interface and makes Project the visible
customer account.

During migration the app:

- retires the Platform Operations and Time Tracking Workspaces plus both standalone booking Pages;
- creates or reuses one customer-number Project for each active Customer and stores the link on Customer;
- reopens an exact completed customer-number Project instead of creating a duplicate;
- keeps permanent customer Projects open with manual progress instead of closing them when all Tasks are done;
- links open, unassigned customer Issues to that canonical Project;
- removes the empty per-Sales-Order provisioning model and ignores an old Sales Order link for canonical
  customer Projects;
- preserves unrelated historical Projects, Working Times, Timesheets, Billing Reviews and Platform Alerts;
- hides the retired operational-state fields instead of deleting their existing values;
- moves the configured time-billing Item to Working Time Settings;
- replaces the visible four-way billing model with the simple **Bill Time** switch while retaining the old
  field only for upgrade compatibility;
- simplifies the Working Time day-close form to the fields needed for start, end, break and allocation.

The customer-project backfill is idempotent and does not guess between unrelated historical Projects.

## Verification

Run the required checks from [AGENTS.md](AGENTS.md):

```bash
docker compose -f ci/compose.yaml run --build --rm quality
docker compose -f ci/compose.yaml run --build --rm integration
docker compose -f ci/compose.yaml down --volumes --remove-orphans
```

## Production releases

Do not run `bench update`, pull a branch or replace the app in the production container. Release a tested
and immutable app tag, pin it in `jitis-erp-platform`, and deploy the resulting platform tag through the
backup-gated Azure workflow documented in that repository's `OPERATIONS.md`.

## Origin and licence

This ERPNext extension is a JITIS-maintained derivative of ALYF GmbH's GPL-licensed
[`working_time`](https://github.com/alyf-de/working_time) app. Original copyright remains with ALYF GmbH
and its contributors; later modifications remain with their respective contributors.

Copyright (C) 2024 ALYF GmbH and contributors. Licensed under GPL-3.0-or-later; see [LICENSE](LICENSE).
