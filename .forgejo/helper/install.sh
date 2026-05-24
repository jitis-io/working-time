#!/bin/bash

set -e

RUNNER_USER=runner
RUNNER_HOME=/home/runner
MYSQL_HOST=mariadb
MYSQL_PORT=3306

if ! id -u "$RUNNER_USER" >/dev/null 2>&1; then
	sudo useradd -m -d "$RUNNER_HOME" -s /bin/bash "$RUNNER_USER"
fi

sudo mkdir -p "$RUNNER_HOME"
sudo chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_HOME"

run_as_runner() {
	sudo -H -u "$RUNNER_USER" env PATH="$PATH" GITHUB_WORKSPACE="$GITHUB_WORKSPACE" bash -lc "$1"
}

cd "$RUNNER_HOME" || exit

sudo apt-get update && sudo apt-get install -y cron redis-server libcups2-dev default-mysql-client

pip install frappe-bench

if command -v corepack >/dev/null 2>&1; then
	corepack enable
	corepack prepare yarn@1.22.22 --activate
else
	npm install -g yarn
fi

run_as_runner "git clone https://github.com/frappe/frappe --branch version-16 --depth 1"
run_as_runner "bench init --skip-assets --frappe-path ~/frappe --python $(which python) frappe-bench"

mysql --host "$MYSQL_HOST" --port "$MYSQL_PORT" -u root -proot -e "SET GLOBAL character_set_server = 'utf8mb4'"
mysql --host "$MYSQL_HOST" --port "$MYSQL_PORT" -u root -proot -e "SET GLOBAL collation_server = 'utf8mb4_unicode_ci'"

mysql --host "$MYSQL_HOST" --port "$MYSQL_PORT" -u root -proot -e "CREATE USER 'test_frappe'@'%' IDENTIFIED BY 'test_frappe'"
mysql --host "$MYSQL_HOST" --port "$MYSQL_PORT" -u root -proot -e "CREATE DATABASE test_frappe"
mysql --host "$MYSQL_HOST" --port "$MYSQL_PORT" -u root -proot -e "GRANT ALL PRIVILEGES ON \`test_frappe\`.* TO 'test_frappe'@'%'"

mysql --host "$MYSQL_HOST" --port "$MYSQL_PORT" -u root -proot -e "FLUSH PRIVILEGES"

cd "$RUNNER_HOME/frappe-bench" || exit

sed -i 's/watch:/# watch:/g' Procfile
sed -i 's/schedule:/# schedule:/g' Procfile
sed -i 's/socketio:/# socketio:/g' Procfile
sed -i 's/redis_socketio:/# redis_socketio:/g' Procfile

run_as_runner "cd ~/frappe-bench && bench get-app erpnext --branch version-16"
run_as_runner "cd ~/frappe-bench && bench get-app hrms --branch version-16"
run_as_runner "cd ~/frappe-bench && bench get-app working_time \"${GITHUB_WORKSPACE}\""

run_as_runner "cd ~/frappe-bench && bench start &> bench_start.log &"
run_as_runner "cd ~/frappe-bench && bench new-site --db-host $MYSQL_HOST --db-root-password root --admin-password admin test_site --install-app erpnext"
run_as_runner "cd ~/frappe-bench && bench --site test_site install-app hrms"
run_as_runner "cd ~/frappe-bench && bench --site test_site install-app working_time"
run_as_runner "cd ~/frappe-bench && bench setup requirements --dev"
