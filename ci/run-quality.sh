#!/usr/bin/env bash

set -euo pipefail

cd /workspace

ruff check --no-cache .
ruff format --check --no-cache .
python -m unittest \
	working_time.test_platform_operations \
	working_time.test_permissions \
	working_time.test_reminders \
	working_time.test_work_cockpit
