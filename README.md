Timetracking and Attendance in ERPNext, integrated with OpenProject

## Who is this for?

Companies that use OpenProject for project management and ERPNext for time tracking and billing.

## Features

- Allows logging of miscellanous time, project time and breaks
- Allows to set a percentage of working time as billable time in a Working Time Log
- Rounds billable time to 5 minutes
- Fetches work package titles from OpenProject (used as time log description)
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
   bench get-app https://github.com/alyf-de/working_time
   bench install-app working_time
   ```

- Create an **OpenProject Site**, enter your _Site URL_, _Username_ and _API Token_
- Enable _Ignore Employee Time Overlap_ and _Ignore User Time Overlap_ in **Projects Settings**
- Open or create an ERPNext **Project**
    - Link it to your **OpenProject Site**
    - Set the _Billing Rate per Hour_
- Create **Activity Cost** records for your **Employees** (_Activity Type_: "Default")
- Create your first **Working Time**
    - Add a time log with description,
    - Add a time log and mark it as a break,
    - Add a time log and link it to a _Project_ and OpenProject _Work Package ID_
- Submit your **Working Time**

## Further Reading

Want to add pretty time logs to your invoice? Check out our [print formats](https://github.com/alyf-de/erpnext_druckformate).

## Platform Operations

The Integration Control Center records OpenProject webhook state, reconciliation runs, billing reviews and project provisioning. Configure a Teams Workflow webhook and the time-billing Item in Platform Operations Settings. Use **Send Teams test alert** after saving the settings. Alerts are sent in the Adaptive Card envelope required by the Teams Workflow webhook. Billing creates drafts only.

Project provisioning creates or links an ERPNext Project and OpenProject Project after an explicit preview. Portal permissions remain owned by the portal instead of being inferred from Keycloak groups.

Run Docker quality and clean-bench integration checks before committing; see AGENTS.md.

## License

ERPNext extension "Working Time": Timetracking and Attendance in ERPNext, integrated with OpenProject.
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
