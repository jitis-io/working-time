Time tracking, attendance and billing review in ERPNext

## Who is this for?

Teams that use ERPNext Projects and Tasks as the single work-management and billing source.

## Features

- Provides one complete daily form with start, end, required/indicated break and unallocated time
- Books duration-first entries against Projects, Tasks and Helpdesk Tickets
- Keeps customer-facing descriptions separate from internal notes
- Allows to set a percentage of working time as billable time in a Working Time Log
- Preserves actual and raw billable time without rounding
- Rounds billable time upward to 15-minute increments only after daily customer/project/task aggregation
- Uses ERPNext Tasks and local customer notes for Timesheet descriptions
- Creates and submits one ERPNext **Timesheet** per employee/day/project after the complete day is validated
- Creates ERPNext **Attendances**
- Report of actual vs. expected working time per Employee
- Sends email reminders to employees for submitting their draft working time entries
    - If a draft working time entry is older than 3 days, and
    - on the last working day of the month
- **Working Time Policy** enforcement per employee, including:
    - Maximum working time per day
    - Mandatory break requirements based on working time thresholds
    - Minimum rest time between days
    - Blocked weekdays
    - Holiday blocking (based on the employee's holiday list)

## Setup

- Install this app

   ```bash
   bench get-app working_time https://github.com/jitis-io/working-time.git
   bench install-app working_time
   ```

- Enable _Ignore Employee Time Overlap_ and _Ignore User Time Overlap_ in **Projects Settings**
- Link each employee login in **Employee > User ID**. Except for System Managers, Working Time lists,
  documents and reports fail closed when this mapping is missing and are restricted to that Employee.
- Open or create an ERPNext **Project**
    - Link it to its customer and source Sales Order
    - Set the _Billing Rate per Hour_
- Create ERPNext **Tasks** for traceable customer and internal work
- Create **Activity Cost** records for your **Employees** (_Activity Type_: "Default")
- Create your first **Working Time**
    - Enter start, end and break,
    - distribute the complete net duration across Projects, Tasks or Helpdesk Tickets,
    - add a customer description and an internal note where useful
- Submit your **Working Time**

## Further Reading

Want to add pretty time logs to your invoice? Check out our [print formats](https://github.com/alyf-de/erpnext_druckformate).

## Platform Operations

The **Platform Operations** workspace groups native ERPNext project provisioning, billing reviews and operational alerts. Configure a Teams Workflow webhook and the time-billing Item in Platform Operations Settings. Use **Send Teams test alert** after saving the settings. Alerts use the Adaptive Card envelope required by Teams Workflow. Billing creates drafts only.

Project provisioning creates or links an ERPNext Project after an explicit preview. Portal permissions remain owned by the portal.

Run Docker quality and clean-bench integration checks before committing; see AGENTS.md.

## Upgrade to 1.2.0

Version 1.2.0 completes the forward-only consolidation on ERPNext:

- Deploy with `bench --site <site> migrate`, `bench build --app working_time`, and `bench restart`.
- The retired external project integration, its DocTypes, credentials, custom fields, jobs, Workspace links and historical integration-control records are removed.
- Sales Order project provisioning creates ERPNext Projects directly.
- Working Time access is employee-scoped for list, read, create, write, submit, cancel, delete, amend and
  both reports. System Managers remain unrestricted; users without an Employee mapping are denied.
- New Working Time submissions preserve raw actual and raw billable hours. Billing Review aggregates billable time by customer, project, task and work date and then rounds the aggregate upward to 15 minutes.
- Creating Sales Invoices leaves the review and its rows at **Draft Created**. Review and submit the invoices manually, then use **Finalize submitted invoices** to mark the review **Invoiced**.
- The migration reclassifies old reviews whose linked Sales Invoices are still drafts. It deliberately does not rewrite historical Timesheet rows: values created by the previous five-minute rounding remain historical records. Correct submitted history only through the normal ERPNext cancellation/amendment process with an audit trail.

## Upgrade to 1.3.0

- Helpdesk 1.28.1 and Telephony are required apps. The internal ticket action **Zeit buchen** records start time and duration without asking the agent for a Project. The server reuses the ticket Project or the only matching open customer Project; ambiguous allocation remains visible in the daily draft and must be resolved before submit. The action is not exposed in the customer portal.
- Projects use native `Project.sales_order` and the explicit billing models Non-billable, Time and Material, Fixed Price and Recurring. Billing Review accepts only T&M projects with a submitted Sales Order and positive hourly rate.
- The migration conflict-checks `source_sales_order`, derives workday fields without rewriting submitted log durations, migrates draft notes and removes the retired fields only after a reference preflight.
- Billing Review still rounds once per customer/project/task/day. Ticket boundaries never create additional rounding.

### ALYF attribution

The daily-form interaction was informed by ALYF GmbH's MIT-licensed `time_capture` project. Its ideas for start/end/break, unallocated time and duration distribution were adapted to this app's v16 data and billing model. `time_capture` itself is not installed or used as a second source of truth. Copyright remains with ALYF GmbH and its contributors.

## License

ERPNext extension "Working Time": time tracking, attendance and billing review in ERPNext.
Copyright (C) 2024 ALYF GmbH and contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
