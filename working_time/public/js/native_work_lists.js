(() => {
	"use strict";

	for (const doctype of ["Task", "Issue"]) {
		const settings = (frappe.listview_settings[doctype] ||= {});
		if (settings.__working_time_views) continue;
		settings.__working_time_views = true;
		const previous_onload = settings.onload;
		const closed = doctype === "Task" ? ["Completed", "Cancelled", "Template"] : ["Closed", "Resolved"];
		const active_filters = () => {
			const filters = [[doctype, "status", "not in", closed]];
			if (doctype === "Task") filters.push([doctype, "is_template", "=", 0]);
			return filters;
		};
		// Retain upstream presentation and actions; broaden only its default status filter.
		settings.filters = (settings.filters || [])
			.filter((filter) => (filter.length === 3 ? filter[0] : filter[1]) !== "status")
			.concat(active_filters());
		settings.onload = function (listview) {
			previous_onload?.call(this, listview);
			if (listview.__working_time_views) return;
			listview.__working_time_views = true;
			const apply = async (kind) => {
				const filters = active_filters();
				const today = frappe.datetime.get_today();
				const due_field = doctype === "Task" ? "exp_end_date" : "resolution_by";
				const date_value = (date) => doctype === "Task" ? date : `${date} 00:00:00`;
				if (kind === "mine") filters.push([doctype, "_assign", "like", `%${JSON.stringify(frappe.session.user)}%`]);
				if (kind === "overdue") filters.push([doctype, due_field, "<", date_value(today)]);
				if (kind === "today" || kind === "week") {
					const weekday = new Date(`${today}T12:00:00`).getDay() || 7;
					const start = kind === "week" ? frappe.datetime.add_days(today, 1 - weekday) : today;
					const end = frappe.datetime.add_days(start, kind === "week" ? 7 : 1);
					filters.push([doctype, due_field, ">=", date_value(start)], [doctype, due_field, "<", date_value(end)]);
				}
				await listview.filter_area.clear(false);
				await listview.filter_area.add(filters);
			};
			for (const [label, kind] of [
				[__("Active work"), "active"],
				[__("Assigned to me"), "mine"],
				[__("Due today"), "today"],
				[__("Due this week"), "week"],
				[__("Overdue"), "overdue"],
			]) {
				listview.page.add_inner_button(label, () => apply(kind), __("Work view"));
			}
		};
	}
})();
