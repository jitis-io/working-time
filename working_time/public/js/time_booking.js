(() => {
	"use strict";

	const namespace = (window.working_time = window.working_time || {});
	let active_dialog = null;
	let opening_promise = null;

	function compact_args(values) {
		return Object.fromEntries(
			Object.entries(values).filter(([, value]) => value !== undefined && value !== null && value !== "")
		);
	}

	function plain_text(value) {
		const parsed = new DOMParser().parseFromString(String(value || ""), "text/html");
		return (parsed.body.textContent || "").replace(/\s+/g, " ").trim();
	}

	function safe_error(error, fallback) {
		return frappe.utils.escape_html(plain_text(error?.message || fallback));
	}

	namespace.plain_text = plain_text;
	namespace.safe_error = safe_error;

	function save_booking(args) {
		return new Promise((resolve, reject) => {
			frappe.xcall("working_time.issues.book_time", args, "POST", {
				error_handlers: {
					// Frappe's native deadlock handler may leave xcall pending. Settle
					// this action so the unchanged dialog and UUID can be retried.
					QueryDeadlockError: () => reject(new Error(__(
						"A concurrent booking interrupted this request. Keep this dialog open and book again with the same values."
					))),
				},
			}).then(resolve, reject);
		});
	}

	function allowed_link_query(doctype, rows, filter) {
		const names = (rows || [])
			.filter(filter || (() => true))
			.map((row) => row.name)
			.filter(Boolean);
		return {
			filters: {
				name: ["in", names.length ? names : ["__working_time_no_match__"]],
			},
		};
	}

	async function start_booked_daily_close_navigation(result) {
		const working_time =
			typeof result?.working_time === "string" ? result.working_time.trim() : "";
		if (!working_time) return false;
		try {
			await frappe.set_route("Form", "Working Time", working_time);
			return true;
		} catch {
			return false;
		}
	}

	async function build_dialog(options) {
		const requested_date = options.date || frappe.datetime.get_today();
		let context;
		try {
			context =
				(await frappe.xcall("working_time.issues.get_time_booking_context", {
					...compact_args({
						project: options.project,
						issue: options.issue,
						task: options.task,
						date: requested_date,
					}),
				})) || {};
		} catch (error) {
			frappe.msgprint({
				title: __("Book time"),
				message: safe_error(error, __("Time booking could not be opened.")),
				indicator: "red",
			});
			return null;
		}

		const fixed_project = Boolean(options.project || options.issue || options.task);
		const fixed_issue = Boolean(options.issue);
		const fixed_task = Boolean(options.task);
		const issues = Array.isArray(context.issues) ? context.issues : [];
		const tasks = Array.isArray(context.tasks) ? context.tasks : [];
		let submitting = false;
		// Keep the same key after a lost response; a retry must not add another row.
		const booking_request_id = crypto.randomUUID();
		let dialog;

		dialog = new frappe.ui.Dialog({
			title: __("Book time"),
			fields: [
				{
					fieldname: "project",
					fieldtype: "Link",
					options: "Project",
					label: __("Project"),
					reqd: 1,
					read_only: fixed_project && Boolean(context.project),
					default: context.project || options.project,
					description: frappe.utils.escape_html(plain_text(context.project_name)),
				},
				{
					fieldname: "date",
					fieldtype: "Date",
					label: __("Date"),
					reqd: 1,
					default: context.date || requested_date,
				},
				{ fieldname: "booking_details", fieldtype: "Section Break" },
				{
					fieldname: "issue",
					fieldtype: "Link",
					options: "Issue",
					label: __("Issue"),
					read_only: fixed_issue,
					default: context.issue || options.issue,
					get_query: () => {
						if (fixed_issue) return {};
						return allowed_link_query("Issue", issues);
					},
				},
				{
					fieldname: "task",
					fieldtype: "Link",
					options: "Task",
					label: __("Task"),
					read_only: fixed_task,
					default: context.task || options.task,
					get_query: () => {
						if (fixed_task) return {};
						const issue = dialog?.get_value("issue");
						return allowed_link_query(
							"Task",
							tasks,
							(row) => !issue || !row.issue || row.issue === issue
						);
					},
				},
				{ fieldname: "duration_column", fieldtype: "Column Break" },
				{
					fieldname: "duration_minutes",
					fieldtype: "Int",
					label: __("Duration (minutes)"),
					reqd: 1,
				},
				{
					fieldname: "billable",
					fieldtype: "Check",
					label: __("Billable"),
					default: context.billable ? 1 : 0,
					read_only: !context.time_billable,
					description: context.time_billable
						? ""
						: __("Enable time billing on the Project to bill these hours."),
				},
				{ fieldname: "notes", fieldtype: "Section Break" },
				{
					fieldname: "customer_description",
					fieldtype: "Small Text",
					label: __("Customer Description"),
				},
				{
					fieldname: "internal_note",
					fieldtype: "Small Text",
					label: __("Internal Note"),
				},
				{
					fieldname: "open_daily_close",
					fieldtype: "Check",
					label: __("Open daily close after booking"),
					default: 0,
					description: __("The daily close for the selected date will open."),
				},
			],
			primary_action_label: __("Book time"),
			primary_action: async () => {
				if (submitting) return;
				const values = dialog.get_values();
				if (!values) return;
				const duration_minutes = Number.parseInt(values.duration_minutes, 10);
				if (!Number.isInteger(duration_minutes) || duration_minutes <= 0) {
					frappe.msgprint({
						title: __("Book time"),
						message: __("Duration must be greater than zero."),
						indicator: "orange",
					});
					return;
				}

				submitting = true;
				const primary_button = dialog.get_primary_btn();
				primary_button.prop("disabled", true).attr("aria-busy", "true");
				try {
					const result = await save_booking({
						...compact_args({
							project: values.project,
							issue: values.issue,
							task: values.task,
							date: values.date,
							duration_minutes,
							customer_description: values.customer_description,
							internal_note: values.internal_note,
							billable: values.billable ? 1 : 0,
							booking_request_id,
						}),
					});
					dialog.hide();
					frappe.show_alert({
						message: __("Time saved in the daily close"),
						indicator: "green",
					});
					if (typeof options.on_booked === "function") {
						try {
							await options.on_booked(result || {});
						} catch {
							frappe.show_alert({
								message: __("Time was booked. Refresh the view to see it."),
								indicator: "orange",
							});
						}
					}
					if (
						values.open_daily_close &&
						!(await start_booked_daily_close_navigation(result))
					) {
						frappe.show_alert({
							message: __(
								"Time was booked, but navigation to the daily close could not be started."
							),
							indicator: "orange",
						});
					}
				} catch (error) {
					frappe.msgprint({
						title: __("Book time"),
						message: safe_error(error, __("Time could not be booked.")),
						indicator: "red",
					});
				} finally {
					submitting = false;
					primary_button.prop("disabled", false).removeAttr("aria-busy");
				}
			},
		});

		const issue_field = dialog.fields_dict.issue;
		const task_field = dialog.fields_dict.task;
		issue_field.df.onchange = () => {
			const selected_issue = dialog.get_value("issue");
			const selected_task = dialog.get_value("task");
			const task = tasks.find((row) => row.name === selected_task);
			if (task && selected_issue && task.issue && task.issue !== selected_issue) {
				dialog.set_value("task", "");
			}
		};
		task_field.df.onchange = () => {
			const task = tasks.find((row) => row.name === dialog.get_value("task"));
			if (task?.issue && !fixed_issue) dialog.set_value("issue", task.issue);
		};

		active_dialog = dialog;
		dialog.$wrapper.one("hidden.bs.modal", () => {
			if (active_dialog === dialog) active_dialog = null;
		});
		dialog.show();
		return dialog;
	}

	namespace.open_time_booking_dialog = async function (options = {}) {
		if (active_dialog) {
			active_dialog.show();
			return active_dialog;
		}
		if (opening_promise) return opening_promise;
		opening_promise = build_dialog(options);
		try {
			return await opening_promise;
		} finally {
			opening_promise = null;
		}
	};
})();
