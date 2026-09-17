import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const scriptPath = path.resolve(
	path.dirname(fileURLToPath(import.meta.url)),
	"../working_time/public/js/project.js"
);
const scriptSource = fs.readFileSync(scriptPath, "utf8");
const conflictMessage =
	"A concurrent request interrupted opening the daily close. Please try again.";

class Element {
	constructor() {
		this.dataValues = {};
		this.properties = {};
		this.attributes = {};
		this.handlers = {};
		this.childElements = [];
	}
	data(key, value) {
		if (arguments.length === 1) return this.dataValues[key];
		this.dataValues[key] = value;
		return this;
	}
	prop(key, value) { this.properties[key] = value; return this; }
	attr(key, value) { this.attributes[key] = value; return this; }
	removeAttr(key) { delete this.attributes[key]; return this; }
	empty() { this.childElements = []; return this; }
	append(child) { this.childElements.push(child); return this; }
	appendTo(parent) { parent.append(this); return this; }
	text(value) { this.label = value; return this; }
	on(event, handler) { this.handlers[event] = handler; return this; }
	children() { return this.childElements; }
	addClass() { return this; }
	toggleClass() { return this; }
	find() { return this; }
	remove() { return this; }
	val(value) {
		if (arguments.length === 0) return this.value;
		this.value = value;
		return this;
	}
}

async function settled(action) {
	let timeout;
	try {
		await Promise.race([
			action,
			new Promise((_, reject) => {
				timeout = setTimeout(() => reject(new Error("Daily close action remained pending")), 500);
			}),
		]);
	} finally {
		clearTimeout(timeout);
	}
}

async function setup(overview = { capabilities: { can_book_time: true } }, createDelivery = false) {
	const elements = [];
	const calls = [];
	const messages = [];
	const routes = [];
	const alerts = [];
	const newDocuments = [];
	const overviewCalls = [];
	let refresh;
	const wrapper = new Element();
	const window = {
		location: { href: "" },
		working_time: { safe_error: (error, fallback) => error?.message || fallback },
	};
	const frappe = {
		ui: { form: { on(doctype, handlers) {
			assert.equal(doctype, "Project");
			refresh = handlers.refresh;
		} } },
		datetime: { get_today: () => "2026-08-31", str_to_user: (value) => value },
		model: { can_create: (doctype) => createDelivery && doctype === "Delivery Note" },
		new_doc: (...args) => newDocuments.push(JSON.parse(JSON.stringify(args))),
		xcall(method, args, type, options) {
			if (method === "working_time.project_overview.get_project_month") {
				overviewCalls.push(JSON.parse(JSON.stringify(args)));
				return Promise.resolve(overview);
			}
			assert.equal(method, "working_time.issues.get_or_create_my_working_time");
			assert.equal(args.date, "2026-08-31");
			return new Promise((resolve, reject) => {
				calls.push({ method, args, type, options, resolve, reject });
			});
		},
		set_route(...route) { routes.push(route); },
		msgprint(message) { messages.push(message); },
		show_alert(alert) { alerts.push(alert); },
	};
	const context = vm.createContext({
		window,
		frappe,
		document: { getElementById: () => ({}) },
		DOMParser: class { parseFromString(value) { return { body: { textContent: value } }; } },
		$: () => { const element = new Element(); elements.push(element); return element; },
		__: (message) => message,
		format_currency: (value) => String(value),
	});
	vm.runInContext(scriptSource, context, { filename: scriptPath });
	refresh({
		doc: { name: "TEST-PROJECT" },
		is_new: () => false,
		fields_dict: { customer_account_overview: { $wrapper: wrapper } },
	});
	await new Promise((resolve) => setImmediate(resolve));
	const button = elements.find((element) => element.label === "Daily close");
	assert.ok(button?.handlers.click, "the real Project toolbar must expose Daily close");
	return { button, calls, messages, routes, alerts, window, elements, newDocuments, overviewCalls };
}

function assertUnlocked(button) {
	assert.equal(button.data("working-time-busy"), false);
	assert.equal(button.properties.disabled, false);
	assert.equal(button.attributes["aria-busy"], undefined);
}

{
	const { button, calls, messages, routes, alerts } = await setup();
	const action = button.handlers.click();
	assert.equal(button.data("working-time-busy"), true);
	assert.equal(button.properties.disabled, true);
	assert.equal(button.attributes["aria-busy"], "true");
	await settled(button.handlers.click());
	assert.equal(calls.length, 1, "a second click must not create another in-flight request");
	calls[0].resolve({ working_time: "WT-TEST-DAILY" });
	await settled(action);
	assertUnlocked(button);
	assert.deepEqual(routes, [["Form", "Working Time", "WT-TEST-DAILY"]]);
	assert.equal(messages.length, 0);
	assert.equal(alerts.length, 0, "opening Daily close must not claim a booking was saved");
}

{
	const { button, calls, messages, routes, alerts } = await setup();
	const action = button.handlers.click();
	// Frappe16.32 dispatches this request-scoped handler during cleanup, while
	// its native QueryDeadlockError path need not reject the xcall Promise.
	// Deliberately leave the first transport Promise unresolved and unrejected.
	calls[0].options?.error_handlers?.QueryDeadlockError({ exc_type: "QueryDeadlockError" });
	await settled(action);
	assertUnlocked(button);
	assert.equal(calls.length, 1, "the client must not automatically retry the request");
	assert.equal(routes.length, 0);
	assert.equal(alerts.length, 0);
	assert.equal(messages.length, 1);
	assert.equal(messages[0].indicator, "red");
	assert.equal(messages[0].message, conflictMessage);
	const retry = button.handlers.click();
	assert.equal(calls.length, 2, "an explicit retry must send a new request after unlocking");
	assert.equal(calls[1].type, "POST");
	calls[1].resolve({ working_time: "WT-TEST-AFTER-CONFLICT" });
	await settled(retry);
	assertUnlocked(button);
	assert.deepEqual(routes, [["Form", "Working Time", "WT-TEST-AFTER-CONFLICT"]]);
	assert.equal(messages.length, 1);
	assert.equal(alerts.length, 0);
}

{
	const { button, calls, messages, routes, alerts } = await setup();
	const action = button.handlers.click();
	calls[0].reject(new Error("Unexpected request failure"));
	await settled(action);
	assertUnlocked(button);
	assert.equal(calls.length, 1);
	assert.equal(routes.length, 0);
	assert.equal(alerts.length, 0);
	assert.equal(messages[0].message, "Unexpected request failure",
		"unknown errors must not be reclassified as a transaction conflict or success");
}

{
	const { button, calls, messages, routes, alerts } = await setup();
	const action = button.handlers.click();
	calls[0].resolve({});
	await settled(action);
	assertUnlocked(button);
	assert.equal(routes.length, 0);
	assert.equal(alerts.length, 0);
	assert.equal(messages[0].message, "No daily working time record is available.");
}

{
	const { elements, newDocuments, routes, calls } = await setup({
		project: { name: "TEST-PROJECT", customer: "TEST-CUSTOMER", company: "TEST-COMPANY" },
		period: { start: "2026-08-01", end: "2026-08-31" },
		capabilities: { can_book_time: true, can_view_deliveries: true },
		summary: { hours: 1, pending_hours: 0.5, unbilled_amount: 120 },
		counts: { pending_time_entries: 1, delivery_notes: 1 },
		rows: {
			pending_time_entries: [{ working_time: "WT-SAVED", date: "2026-08-17", hours: 0.5, description: "Saved service" }],
			delivery_notes: [{ name: "DN-1", posting_date: "2026-08-17", status: "Partially Billed", docstatus: 1, per_billed: 50 }],
		},
	}, true);
	const labelled = (label) => elements.find((element) => element.label === label);
	assert.ok(labelled(`${(1.5).toLocaleString(undefined, { maximumFractionDigits: 2 })} h`), "recorded total includes pending duration");
	assert.ok(labelled("120"), "pending hours do not invent a new billing amount");
	assert.ok(labelled("Saved service"));
	assert.ok(labelled("50%"));
	await labelled("Record delivery").handlers.click();
	assert.deepEqual(newDocuments, [["Delivery Note", {
		customer: "TEST-CUSTOMER", company: "TEST-COMPANY", project: "TEST-PROJECT",
	}]]);
	await labelled("All delivery notes").handlers.click();
	assert.deepEqual(JSON.parse(JSON.stringify(routes.at(-1))), ["List", "Delivery Note", {
		project: "TEST-PROJECT", customer: "TEST-CUSTOMER",
	}]);
	labelled("2026-08-17").handlers.click({ preventDefault() {} });
	assert.deepEqual(routes.at(-1), ["Form", "Working Time", "WT-SAVED"]);
	await labelled("Open daily records").handlers.click();
	assert.deepEqual(JSON.parse(JSON.stringify(routes.at(-1))), ["List", "Working Time", {
		docstatus: 0, date: ["between", ["2026-08-01", "2026-08-31"]],
	}]);
	assert.equal(calls.length, 0, "overview navigation must not create time or submit stock");
}

{
	const { elements } = await setup();
	assert.equal(elements.some((element) => element.label === "Record delivery"), false);
	assert.equal(elements.some((element) => element.label === "All delivery notes"), false);
	assert.equal(elements.some((element) => element.label === "Saved time awaiting daily close"), false);
}

{
	const { window, elements, overviewCalls, calls, messages } = await setup();
	assert.equal(overviewCalls.at(-1).month, "2026-08");
	window.working_time.open_time_booking_dialog = async (options) => {
		await options.on_booked({ working_time: "WT-JULY" }, { date: "2026-07-14" });
	};
	await elements.find((element) => element.label === "Book time").handlers.click();
	assert.deepEqual(overviewCalls.at(-1), { project: "TEST-PROJECT", month: "2026-07" },
		"a saved entry for an earlier month must load that month so the entry is visible");
	assert.equal(calls.length, 0, "refreshing a saved entry must not create another daily record");
	assert.equal(messages.length, 0);
}

console.log("project.js runtime semantics: 7 scenarios passed");
