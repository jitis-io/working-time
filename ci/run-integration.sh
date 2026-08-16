#!/usr/bin/env bash

set -euo pipefail

readonly APP_DIR="${APP_DIR:-/workspace}"
readonly BENCH_DIR="${BENCH_DIR:-/home/runner/frappe-bench}"
readonly DB_HOST="${DB_HOST:-mariadb}"
readonly DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
readonly DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-root}"
readonly SITE_NAME="${SITE_NAME:-test_site}"
readonly FRAPPE_COMMIT="6a329d068416768ec47ccd3326b9cc95a8d7bf99"
readonly ERPNEXT_COMMIT="21d187302045476f1ceb5d0d86219389ab1e75b8"
readonly HRMS_COMMIT="f281e8b172ac8836ad89c59df65a922101103097"

until mariadb-admin ping --host="$DB_HOST" --user=root --password="$DB_ROOT_PASSWORD" --silent; do
	sleep 2
done

redis-server --daemonize yes --port 13000 --save "" --appendonly no
redis-server --daemonize yes --port 11000 --save "" --appendonly no

# Keep Bench's own Git operations outside the mounted source checkout. A local
# Git worktree uses a host-only .git pointer that is intentionally unavailable
# inside the disposable CI container.
cd /home/runner
bench init \
	--frappe-branch v16.31.0 \
	--python "$(command -v python)" \
	--skip-assets \
	--skip-redis-config-generation \
	"$BENCH_DIR"

cd "$BENCH_DIR"
test "$(git -C apps/frappe rev-parse HEAD)" = "$FRAPPE_COMMIT"

bench get-app --skip-assets --branch v16.32.1 erpnext https://github.com/frappe/erpnext.git
test "$(git -C apps/erpnext rev-parse HEAD)" = "$ERPNEXT_COMMIT"
bench get-app --skip-assets --branch v16.16.0 hrms https://github.com/frappe/hrms.git
test "$(git -C apps/hrms rev-parse HEAD)" = "$HRMS_COMMIT"
bench get-app --skip-assets --soft-link working_time "$APP_DIR"
bench setup requirements --dev

bench new-site \
	--db-host "$DB_HOST" \
	--db-root-username "$DB_ROOT_USERNAME" \
	--db-root-password "$DB_ROOT_PASSWORD" \
	--admin-password admin \
	--install-app erpnext \
	--install-app hrms \
	"$SITE_NAME"

bench --site "$SITE_NAME" install-app working_time
bench set-config --global chromium_path "$(command -v chromium)"
bench --site "$SITE_NAME" migrate
bench build --app working_time
bench --site "$SITE_NAME" set-config allow_tests true
bench --site "$SITE_NAME" run-tests --app working_time
