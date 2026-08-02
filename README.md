Time tracking, attendance and billing review in ERPNext

## Who is this for?

Teams that use ERPNext Projects and Tasks as the ongoing work-management and billing source. OpenProject remains available only for the controlled final import.

## Features

- Allows logging of miscellanous time, project time and breaks
- Allows to set a percentage of working time as billable time in a Working Time Log
- Preserves actual and raw billable time without rounding
- Rounds billable time upward to 15-minute increments only after daily customer/project/task aggregation
- Uses ERPNext Tasks and local customer notes for Timesheet descriptions without a runtime OpenProject lookup
- Creates ERPNext **Timesheets**
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
   bench get-app --branch version-16 working_time ssh://git@git-ssh.jitis.io:2222/jitis/erpnext/working_time.git
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
    - Add a time log with description,
    - Add a time log and mark it as a break,
    - Add a time log and link it to a _Project_ and _Task_
- Submit your **Working Time**

## Further Reading

Want to add pretty time logs to your invoice? Check out our [print formats](https://github.com/alyf-de/erpnext_druckformate).

## Platform Operations

The Integration Control Center records OpenProject webhook state, reconciliation runs, billing reviews and project provisioning. Configure a Teams Workflow webhook and the time-billing Item in Platform Operations Settings. Use **Send Teams test alert** after saving the settings. Alerts are sent in the Adaptive Card envelope required by the Teams Workflow webhook. Billing creates drafts only.

OpenProject reconciliation is intentionally not scheduled. For the controlled final import, open the **OpenProject Site** and use **Queue one-time reconciliation** as a System Manager. Run the required types deliberately and review each result in the Integration Control Center. Do not enable full deletion reconciliation unless the API account can see every source record.

OpenProject webhooks fail closed: requests are rejected when the configured site has no webhook secret. A pull-only final import does not require a webhook secret, but no webhook can be accepted until one is configured.

Project provisioning creates or links only the ERPNext Project after an explicit preview. It no longer creates OpenProject projects. Portal permissions remain owned by the portal.

Run Docker quality and clean-bench integration checks before committing; see AGENTS.md.

## Upgrade to 1.1.0

Version 1.1.0 is a forward-only transition away from OpenProject as the ongoing work-management source:

- Deploy with `bench --site <site> migrate`, `bench build --app working_time`, and `bench restart`.
- OpenProject webhook requests now require a configured signature secret and otherwise fail closed.
- Automatic OpenProject reconciliation jobs were removed. If a final import is still required, queue each required reconciliation once from the OpenProject Site and inspect the run before continuing.
- Sales Order project provisioning creates only ERPNext Projects and never creates new OpenProject projects.
- Working Time access is employee-scoped for list, read, create, write, submit, cancel, delete, amend and
  both reports. System Managers remain unrestricted; users without an Employee mapping are denied.
- New Working Time submissions preserve raw actual and raw billable hours. Billing Review aggregates billable time by customer, project, task and work date and then rounds the aggregate upward to 15 minutes.
- Creating Sales Invoices leaves the review and its rows at **Draft Created**. Review and submit the invoices manually, then use **Finalize submitted invoices** to mark the review **Invoiced**.
- The migration reclassifies old reviews whose linked Sales Invoices are still drafts. It deliberately does not rewrite historical Timesheet rows: values created by the previous five-minute rounding remain historical records. Correct submitted history only through the normal ERPNext cancellation/amendment process with an audit trail.

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
