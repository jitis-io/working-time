#!/usr/bin/env bash

set -euo pipefail

cd /workspace

ruff check --no-cache .
ruff format --check --no-cache .
node --check working_time/working_time/page/work_cockpit/work_cockpit.js
node --check working_time/working_time/page/working_time_quick_entry/working_time_quick_entry.js
node --check working_time/public/js/task.js
python -m unittest \
	working_time.test_platform_operations \
	working_time.test_permissions \
	working_time.test_reminders \
	working_time.test_issues \
	working_time.test_work_cockpit
