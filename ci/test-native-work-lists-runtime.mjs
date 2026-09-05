import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../working_time/public/js/native_work_lists.js", import.meta.url), "utf8");
const nativeCalls = [];
const frappe = {
	listview_settings: Object.fromEntries(["Task", "Issue"].map((doctype) => [doctype, {
		filters: [["status", "=", "Open"]],
		get_indicator: () => "native",
		onload: () => nativeCalls.push(doctype),
	}])),
	session: { user: "person@example.invalid" },
	datetime: {
		get_today: () => "2026-09-05",
		add_days: (day, days) => {
			const date = new Date(`${day}T12:00:00Z`);
			date.setUTCDate(date.getUTCDate() + days);
			return date.toISOString().slice(0, 10);
		},
	},
};
const context = vm.createContext({ frappe, __: (message) => message });
vm.runInContext(source, context);
vm.runInContext(source, context);
for (const doctype of ["Task", "Issue"]) {
	const buttons = new Map();
	let filters;
	const events = [];
	const listview = {
		page: { add_inner_button: (label, action, group) => {
			assert.equal(group, "Work view");
			assert.equal(buttons.has(label), false);
			buttons.set(label, action);
		} },
		filter_area: {
			clear: async (refresh) => { assert.equal(refresh, false); events.push("clear"); },
			add: async (value) => { events.push("add"); filters = JSON.parse(JSON.stringify(value)); },
		},
	};
	frappe.listview_settings[doctype].onload(listview);
	assert.equal(frappe.listview_settings[doctype].get_indicator(), "native");
	assert.equal(nativeCalls.filter((d) => d === doctype).length, 1);
	assert.equal(buttons.size, 5);
	await buttons.get("Active work")();
	assert.deepEqual(events, ["clear", "add"]);
	assert.deepEqual(filters[0], [doctype, "status", "not in", doctype === "Task" ? ["Completed", "Cancelled", "Template"] : ["Closed", "Resolved"]]);
	await buttons.get("Assigned to me")();
	assert.deepEqual(filters.at(-1), [doctype, "_assign", "like", '%"person@example.invalid"%']);
	const dueField = doctype === "Task" ? "exp_end_date" : "resolution_by";
	const suffix = doctype === "Task" ? "" : " 00:00:00";
	await buttons.get("Due today")();
	assert.deepEqual(filters.slice(-2), [[doctype, dueField, ">=", `2026-09-05${suffix}`], [doctype, dueField, "<", `2026-09-06${suffix}`]]);
	await buttons.get("Due this week")();
	assert.deepEqual(filters.slice(-2), [[doctype, dueField, ">=", `2026-08-31${suffix}`], [doctype, dueField, "<", `2026-09-07${suffix}`]]);
	await buttons.get("Overdue")();
	assert.deepEqual(filters.at(-1), [doctype, dueField, "<", `2026-09-05${suffix}`]);
}
console.log("Native work list filters preserve upstream actions and date/identity boundaries.");
