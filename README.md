# Working Time

Project-centred time capture and billing preparation for ERPNext v16.

The technical app and Python package remain named `working_time` for upgrade compatibility. The app
does not provide a second workplace or project-management model. ERPNext **Project** is the visible
customer account and the single entry point for tickets, tasks, time, purchases and billing.

## Operating model

```text
Customer -> permanent customer Project -> Issue or Task -> time booking
                                      -> Purchase Invoice costs
                                      -> monthly Project overview
                                      -> reviewed Sales Invoice draft
```

- Every active Customer has one permanent customer Project. Its visible project name is the ERPNext
  customer number. Historical job Projects remain untouched and are not merged automatically.
- An Issue is incoming work. A Task is only needed for planned or multi-step work.
- **Book time** on Project, Issue or Task adds a duration-first row to the current employee's daily
  Working Time draft.
- **Day close** opens that one daily Working Time record. Start, end, break and the complete allocation
  are checked once before submit.
- Submitting Working Time creates Attendance and one ERPNext Timesheet per employee, day and Project.
  Do not create Timesheets manually.
- Purchase Invoice rows carry the customer Project. ERPNext and the Project month view then show the
  net cost in company currency.
- **Create time invoice draft** uses the visible monthly preview and opens exactly one draft Sales
  Invoice for eligible time. It never submits or sends anything. A separate **Sales invoice** action
  covers recurring fees and manually reviewed pass-through costs.
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

## Upgrade to 1.8.2

Version 1.8.2 makes the duration-first workflow more direct without changing any billing or
submission behavior:

- **Book time** can optionally open the exact daily Working Time record returned by the server;
- existing post-booking callbacks still run before navigation;
- a navigation failure is reported separately and never misrepresents the already saved time as a
  failed booking.

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
