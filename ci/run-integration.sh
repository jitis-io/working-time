#!/usr/bin/env bash

set -euo pipefail

readonly APP_DIR="${APP_DIR:-/workspace}"
readonly APP_SOURCE_DIR="/home/runner/working_time"
readonly BENCH_DIR="${BENCH_DIR:-/home/runner/frappe-bench}"
readonly DB_HOST="${DB_HOST:-mariadb}"
readonly DB_ROOT_USERNAME="${DB_ROOT_USERNAME:-root}"
readonly DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-root}"
readonly SITE_NAME="${SITE_NAME:-test_site}"
readonly FRAPPE_COMMIT="5cba016e86b54b57f34a3864282b92300ef20fb0"
readonly ERPNEXT_COMMIT="b24c9eba551905e256e336ff170a91a92d197a2f"
readonly HRMS_COMMIT="519a078131f7f96f8313b405caa511a1229a98f9"

until mariadb-admin ping --host="$DB_HOST" --user=root --password="$DB_ROOT_PASSWORD" --silent; do
	sleep 2
done

redis-server --daemonize yes --port 13000 --save "" --appendonly no
redis-server --daemonize yes --port 11000 --save "" --appendonly no

# Bench get-app requires usable local Git metadata, even with --soft-link.
# A Windows worktree's .git file points outside the image. Build an isolated
# source copy without host metadata; never initialise or modify the host tree.
mkdir -p "$APP_SOURCE_DIR"
tar -C "$APP_DIR" --exclude='./.git' -cf - . | tar -C "$APP_SOURCE_DIR" -xf -
git -C "$APP_SOURCE_DIR" init --quiet
# Bench also inspects HEAD. This is disposable fixture metadata, not a commit
# to the user's worktree or any remote repository.
git -C "$APP_SOURCE_DIR" add .
git -C "$APP_SOURCE_DIR" -c user.name='Disposable CI' -c user.email='ci@example.invalid' \
	commit --quiet -m 'Disposable integration source snapshot'

# Keep Bench's own Git operations outside the source checkout.
cd /home/runner
bench init \
	--frappe-branch v16.32.0 \
	--python "$(command -v python)" \
	--skip-assets \
	--skip-redis-config-generation \
	"$BENCH_DIR"

cd "$BENCH_DIR"
test "$(git -C apps/frappe rev-parse HEAD)" = "$FRAPPE_COMMIT"

bench get-app --skip-assets --branch v16.33.0 erpnext https://github.com/frappe/erpnext.git
test "$(git -C apps/erpnext rev-parse HEAD)" = "$ERPNEXT_COMMIT"
bench get-app --skip-assets --branch v16.17.0 hrms https://github.com/frappe/hrms.git
test "$(git -C apps/hrms rev-parse HEAD)" = "$HRMS_COMMIT"
bench get-app --skip-assets --soft-link "$APP_SOURCE_DIR"
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
# Re-running normal migration must preserve the installed schema and data.
bench --site "$SITE_NAME" migrate
bench build --app working_time
bench --site "$SITE_NAME" set-config allow_tests true
bench --site "$SITE_NAME" run-tests --app working_time
