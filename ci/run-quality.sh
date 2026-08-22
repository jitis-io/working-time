#!/usr/bin/env bash

set -euo pipefail

cd /workspace

ruff check --no-cache .
ruff format --check --no-cache .
for script in working_time/public/js/*.js; do
	node --check "$script"
done
pybabel compile \
	--input-file working_time/locale/de.po \
	--output-file /tmp/working-time-de.mo
pybabel compile \
	--input-file working_time/locale/en.po \
	--output-file /tmp/working-time-en.mo
python -m unittest \
	working_time.test_platform_operations \
	working_time.test_permissions \
	working_time.test_reminders \
	working_time.test_issues \
	working_time.test_customer_project_patches \
	working_time.test_customer_projects \
	working_time.test_client_scripts \
	working_time.test_project_overview
