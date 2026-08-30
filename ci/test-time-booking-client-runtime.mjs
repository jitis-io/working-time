import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { webcrypto } from "node:crypto";
import { fileURLToPath } from "node:url";

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
const scriptPath = path.resolve(
	currentDirectory,
	"../working_time/public/js/time_booking.js"
);
const scriptSource = fs.readFileSync(scriptPath, "utf8");
const navigationWarning =
	"Time was booked, but navigation to the daily close could not be started.";

function makeButton() {
	const button = {
		prop() {
			return button;
		},
		attr() {
			return button;
		},
		removeAttr() {
			return button;
		},
	};
	return button;
}

async function runScenario({
	bookingResult,
	openDailyClose = true,
	callback = "none",
	routeRejects = false,
	lostResponse = false,
	doubleClick = false,
	transactionConflict = false,
}) {
	const events = [];
	const alerts = [];
	const messages = [];
	const routes = [];
	const bookingArgs = [];
	let dialog;

	class Dialog {
		constructor(configuration) {
			this.configuration = configuration;
			this.values = {
				project: "P-1",
				date: "2026-08-28",
				duration_minutes: 30,
				billable: 0,
				open_daily_close: openDailyClose ? 1 : 0,
			};
			this.fields_dict = { issue: { df: {} }, task: { df: {} } };
			this.$wrapper = { one() {} };
			dialog = this;
		}

		get_values() {
			return { ...this.values };
		}

		get_value(fieldname) {
			return this.values[fieldname];
		}

		set_value(fieldname, value) {
			this.values[fieldname] = value;
		}

		get_primary_btn() {
			return makeButton();
		}

		hide() {
			events.push("dialog:hide");
		}

		show() {
			events.push("dialog:show");
		}
	}

	const frappe = {
		datetime: {
			get_today: () => "2026-08-28",
		},
		utils: {
			escape_html: (value) => String(value),
		},
		ui: { Dialog },
		async xcall(method, args, type, options) {
			if (method === "working_time.issues.get_time_booking_context") {
				return {
					project: "P-1",
					date: "2026-08-28",
					issues: [],
					tasks: [],
				};
			}
			if (method === "working_time.issues.book_time") {
				bookingArgs.push(args);
				if (transactionConflict && bookingArgs.length === 1) {
					options.error_handlers.QueryDeadlockError();
					// Exact native v16 shape: exception handler need not reject xcall.
					return new Promise(() => {});
				}
				events.push("booking:saved");
				if (lostResponse && bookingArgs.length === 1) throw new Error("response lost");
				return bookingResult;
			}
			throw new Error(`Unexpected xcall: ${method}`);
		},
		async set_route(...route) {
			routes.push(route);
			events.push("navigation:start");
			if (routeRejects) throw new Error("router rejected route");
		},
		show_alert(alert) {
			alerts.push(alert);
			events.push(`alert:${alert.indicator}:${alert.message}`);
		},
		msgprint(message) {
			messages.push(message);
			events.push(`message:${message.indicator}:${message.message}`);
		},
	};

	class DOMParser {
		parseFromString(value) {
			return { body: { textContent: String(value).replace(/<[^>]*>/g, "") } };
		}
	}

	const context = vm.createContext({
		window: {},
		frappe,
		DOMParser,
		crypto: webcrypto,
		__: (message) => message,
	});
	vm.runInContext(scriptSource, context, { filename: scriptPath });

	const options = {};
	if (callback !== "none") {
		options.on_booked = async () => {
			events.push("callback:start");
			if (callback === "reject") throw new Error("callback rejected");
			events.push("callback:complete");
		};
	}

	await context.window.working_time.open_time_booking_dialog(options);
	assert.ok(dialog, "the booking dialog should be constructed");
	if (doubleClick) {
		await Promise.all([dialog.configuration.primary_action(), dialog.configuration.primary_action()]);
	} else {
		await dialog.configuration.primary_action();
	}
	if (lostResponse || transactionConflict) await dialog.configuration.primary_action();

	return { events, alerts, messages, routes, bookingArgs };
}

function assertNoRedBookingError(result) {
	assert.equal(
		result.messages.some((message) => message.indicator === "red"),
		false,
		"navigation handling must not re-enter the red booking error path"
	);
}

{
	const result = await runScenario({
		bookingResult: { working_time: "WT-2026-00001" },
		callback: "resolve",
	});
	assert.ok(
		result.events.indexOf("callback:complete") < result.events.indexOf("navigation:start"),
		"the existing callback must complete before optional navigation starts"
	);
	assert.deepEqual(result.routes, [["Form", "Working Time", "WT-2026-00001"]]);
}

{
	const result = await runScenario({
		bookingResult: { working_time: "WT-2026-00002" },
		callback: "reject",
	});
	assert.ok(
		result.events.indexOf("callback:start") < result.events.indexOf("navigation:start"),
		"a rejected callback must not prevent optional navigation"
	);
	assert.equal(result.routes.length, 1);
	assertNoRedBookingError(result);
}

{
	const result = await runScenario({ bookingResult: {} });
	assert.equal(result.routes.length, 0, "a missing Working Time name must not create a route");
	assert.equal(
		result.alerts.some(
			(alert) => alert.indicator === "orange" && alert.message === navigationWarning
		),
		true
	);
	assertNoRedBookingError(result);
}

{
	const result = await runScenario({
		bookingResult: { working_time: "WT-2026-00003" },
		routeRejects: true,
	});
	assert.deepEqual(result.routes, [["Form", "Working Time", "WT-2026-00003"]]);
	assert.equal(
		result.alerts.some(
			(alert) => alert.indicator === "orange" && alert.message === navigationWarning
		),
		true
	);
	assertNoRedBookingError(result);
}

{
	const result = await runScenario({
		bookingResult: { working_time: "WT-2026-00004" },
		openDailyClose: false,
	});
	assert.equal(result.routes.length, 0, "an unchecked option must not navigate");
	assert.equal(
		result.alerts.some((alert) => alert.message === navigationWarning),
		false,
		"an unchecked option must not emit a navigation warning"
	);
	assertNoRedBookingError(result);
}

{
	const result = await runScenario({
		bookingResult: { working_time: "WT-RETRY" },
		lostResponse: true,
	});
	assert.equal(result.bookingArgs.length, 2);
	assert.match(result.bookingArgs[0].booking_request_id, /^[0-9a-f-]{36}$/);
	assert.equal(result.bookingArgs[0].booking_request_id, result.bookingArgs[1].booking_request_id,
		"retry after a lost response must reuse the same booking identity");
}

{
	const result = await runScenario({ bookingResult: { working_time: "WT-DOUBLE" }, doubleClick: true });
	assert.equal(result.bookingArgs.length, 1, "a double click must send only one request");
}

{
	const result = await runScenario({ bookingResult: { working_time: "WT-CONFLICT" }, transactionConflict: true });
	assert.equal(result.bookingArgs.length, 2, "a native transaction conflict must release the action for retry");
	assert.equal(result.bookingArgs[0].booking_request_id, result.bookingArgs[1].booking_request_id);
	assert.equal(result.messages.length, 1);
	assert.match(result.messages[0].message, /concurrent booking interrupted/);
	assert.equal(result.events.filter((event) => event === "dialog:hide").length, 1);
	assert.equal(result.alerts.filter((alert) => alert.indicator === "green").length, 1);
}

console.log("time_booking.js runtime semantics: 8 scenarios passed");
