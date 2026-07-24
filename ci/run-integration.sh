#!/usr/bin/env bash

set -euo pipefail

readonly APP_DIR="${APP_DIR:-/workspace}"
readonly BENCH_DIR="${BENCH_DIR:-/home/runner/frappe-bench}"
readonly DB_HOST="${DB_HOST:-mariadb}"
readonly DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
readonly DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-root}"
readonly SITE_NAME="${SITE_NAME:-test_site}"

until mariadb-admin ping --host="$DB_HOST" --user=root --password="$DB_ROOT_PASSWORD" --silent; do
	sleep 2
done

redis-server --daemonize yes --port 13000 --save "" --appendonly no
redis-server --daemonize yes --port 11000 --save "" --appendonly no

bench init \
	--frappe-branch version-16 \
	--python "$(command -v python)" \
	--skip-assets \
	--skip-redis-config-generation \
	"$BENCH_DIR"

cd "$BENCH_DIR"

bench get-app --branch version-16 erpnext https://github.com/frappe/erpnext.git
bench get-app --branch version-16 hrms https://github.com/frappe/hrms.git
bench get-app --soft-link working_time "$APP_DIR"
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
