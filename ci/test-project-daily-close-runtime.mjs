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

async function setup() {
	const elements = [];
	const calls = [];
	const messages = [];
	const routes = [];
	const alerts = [];
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
		datetime: { get_today: () => "2026-08-31" },
		model: { can_create: () => false },
		xcall(method, args, type, options) {
			if (method === "working_time.project_overview.get_project_month") {
				return Promise.resolve({ capabilities: { can_book_time: true } });
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
	return { button, calls, messages, routes, alerts, window };
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

console.log("project.js Daily close runtime semantics: 4 scenarios passed");
