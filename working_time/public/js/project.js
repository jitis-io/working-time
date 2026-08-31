(() => {
	"use strict";

	const overview_field = "customer_account_overview";
	const state_key = "__working_time_project_overview";

	frappe.ui.form.on("Project", {
		refresh(frm) {
			const wrapper = get_wrapper(frm);
			if (!wrapper) return;
			ensure_styles();
			if (frm.is_new()) {
				wrapper.empty().append(
					$("<div class='text-muted small'></div>").text(
						__("Save the project to open its monthly account.")
					)
				);
				return;
			}
			const state = get_state(frm);
			load_overview(frm, state.month);
		},
	});

	function get_wrapper(frm) {
		return frm.fields_dict[overview_field]?.$wrapper || null;
	}

	function get_state(frm) {
		if (!frm[state_key]) {
			frm[state_key] = {
				month: frappe.datetime.get_today().slice(0, 7),
				request_id: 0,
			};
		}
		return frm[state_key];
	}

	function ensure_styles() {
		if (document.getElementById("working-time-project-overview-styles")) return;
		$("<style id='working-time-project-overview-styles'></style>")
			.text(`
				.wt-project-overview { display: grid; gap: 18px; padding: 2px 0 18px; }
				.wt-project-overview__header { border: 1px solid var(--border-color); border-radius: 10px; padding: 16px; background: var(--fg-color); }
				.wt-project-overview__heading,
				.wt-project-overview__meta,
				.wt-project-overview__toolbar,
				.wt-project-overview__actions,
				.wt-project-overview__action-group,
				.wt-project-overview__relation { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
				.wt-project-overview__heading { justify-content: space-between; align-items: flex-start; gap: 16px; }
				.wt-project-overview__heading h3 { margin: 0 0 5px; font-size: 1.25rem; }
				.wt-project-overview__meta { color: var(--text-muted); font-size: var(--text-sm); }
				.wt-project-overview__status { display: inline-flex; align-items: center; min-height: 24px; padding: 2px 9px; border-radius: 999px; font-size: var(--text-xs); font-weight: 600; background: var(--control-bg); color: var(--text-muted); }
				.wt-project-overview__status--enabled { background: var(--bg-green, #e4f5eb); color: var(--green-700, #16794b); }
				.wt-project-overview__toolbar { justify-content: space-between; align-items: flex-end; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border-color); }
				.wt-project-overview__month { width: 180px; }
				.wt-project-overview__month label { display: block; margin-bottom: 5px; }
				.wt-project-overview__actions { justify-content: flex-end; }
				.wt-project-overview__action-group + .wt-project-overview__action-group { padding-left: 8px; border-left: 1px solid var(--border-color); }
				.wt-project-overview__kpis { display: grid; grid-template-columns: repeat(5, minmax(140px, 1fr)); gap: 10px; }
				.wt-project-overview__kpi { border: 1px solid var(--border-color); border-radius: 9px; padding: 13px 14px; min-width: 0; background: var(--fg-color); }
				.wt-project-overview__kpi-value { margin: 3px 0 2px; font-size: 1.25rem; font-weight: 600; line-height: 1.3; overflow-wrap: anywhere; }
				.wt-project-overview__section { min-width: 0; }
				.wt-project-overview__section-title { display: flex; align-items: baseline; gap: 7px; margin-bottom: 8px; }
				.wt-project-overview__section-title h4 { margin: 0; font-size: 1rem; }
				.wt-project-overview__count { color: var(--text-muted); font-size: var(--text-sm); }
				.wt-project-overview__empty { padding: 13px 14px; border: 1px dashed var(--border-color); border-radius: 8px; background: var(--control-bg); }
				.wt-project-overview .table { margin-bottom: 0; }
				.wt-project-overview td { vertical-align: middle; }
				.wt-project-overview__description { min-width: 180px; max-width: 360px; white-space: normal; }
				@media (max-width: 1199px) {
					.wt-project-overview__kpis { grid-template-columns: repeat(3, minmax(140px, 1fr)); }
				}
				@media (max-width: 767px) {
					.wt-project-overview__heading,
					.wt-project-overview__toolbar { align-items: stretch; flex-direction: column; }
					.wt-project-overview__month { width: 100%; }
					.wt-project-overview__actions { width: 100%; justify-content: flex-start; }
					.wt-project-overview__action-group + .wt-project-overview__action-group { padding-left: 0; border-left: 0; }
					.wt-project-overview__actions .btn { flex: 1 1 auto; }
					.wt-project-overview__kpis { grid-template-columns: repeat(2, minmax(130px, 1fr)); }
					.wt-project-overview__description { min-width: 220px; }
				}
				@media (max-width: 479px) {
					.wt-project-overview__kpis { grid-template-columns: 1fr; }
				}
			`)
			.appendTo(document.head);
	}

	async function load_overview(frm, month) {
		const wrapper = get_wrapper(frm);
		if (!wrapper) return;
		const state = get_state(frm);
		state.month = month;
		const request_id = ++state.request_id;
		wrapper
			.empty()
			.attr("aria-busy", "true")
			.append(
				$("<div class='text-muted small py-3' role='status'></div>").text(
					__("Loading monthly account…")
				)
			);

		try {
			const data = await frappe.xcall("working_time.project_overview.get_project_month", {
				project: frm.doc.name,
				month,
			});
			if (request_id !== state.request_id) return;
			state.month = data?.period?.month || month;
			render_overview(frm, data || {});
		} catch (error) {
			if (request_id !== state.request_id) return;
			render_error(frm, error);
		}
	}

	function render_error(frm, error) {
		const wrapper = get_wrapper(frm);
		wrapper.removeAttr("aria-busy").empty();
		const alert = $("<div class='alert alert-danger mb-0' role='alert'></div>").appendTo(wrapper);
		$("<div></div>")
			.text(plain_text(error?.message || __("The monthly account could not be loaded.")))
			.appendTo(alert);
		const retry = $("<button type='button' class='btn btn-default btn-sm mt-2'></button>")
			.text(__("Try again"))
			.appendTo(alert);
		retry.on("click", () => run_locked(retry, () => load_overview(frm, get_state(frm).month)));
	}

	function render_overview(frm, data) {
		const wrapper = get_wrapper(frm);
		wrapper.removeAttr("aria-busy").empty();
		const root = $("<div class='wt-project-overview'></div>").appendTo(wrapper);
		const project = data.project || {};
		const capabilities = data.capabilities || {};
		const counts = data.counts || {};
		const rows = data.rows || {};

		const header = $("<section class='wt-project-overview__header'></section>").appendTo(root);
		const heading = $("<div class='wt-project-overview__heading'></div>").appendTo(header);
		const heading_copy = $("<div></div>").appendTo(heading);
		$("<h3></h3>").text(__("Monthly account")).appendTo(heading_copy);
		const identifiers = [project.project_name || project.name];
		if (project.customer && !identifiers.includes(project.customer)) identifiers.push(project.customer);
		const meta = $("<div class='wt-project-overview__meta'></div>").appendTo(heading_copy);
		$("<span></span>").text(identifiers.filter(Boolean).join(" · ")).appendTo(meta);
		$("<span aria-hidden='true'>·</span>").appendTo(meta);
		$("<span></span>")
			.text(
				__("{0} open issues · {1} open tasks", [
					Number(counts.open_issues || 0),
					Number(counts.open_tasks || 0),
				])
			)
			.appendTo(meta);
		$("<span class='wt-project-overview__status'></span>")
			.toggleClass("wt-project-overview__status--enabled", Boolean(project.time_billable))
			.text(project.time_billable ? __("Time billing enabled") : __("Time billing disabled"))
			.appendTo(heading);

		render_toolbar(frm, header, data);
		render_kpis(root, data);
		render_time_table(root, rows.time_entries || [], project.currency);
		if (capabilities.can_view_purchases) {
			render_invoice_table({
				root,
				title: __("Purchase invoices"),
				doctype: "Purchase Invoice",
				rows: rows.purchase_invoices || [],
				count: counts.purchase_invoices,
				party_key: "supplier_name",
				party_fallback: "supplier",
				currency: project.currency,
			});
		}
		if (capabilities.can_view_sales) {
			render_invoice_table({
				root,
				title: __("Sales invoices"),
				doctype: "Sales Invoice",
				rows: rows.sales_invoices || [],
				count: counts.sales_invoices,
				party_key: "customer",
				party_fallback: "customer",
				currency: project.currency,
			});
		}
	}

	function render_toolbar(frm, header, data) {
		const toolbar = $("<div class='wt-project-overview__toolbar'></div>").appendTo(header);
		const month_group = $("<div class='wt-project-overview__month'></div>").appendTo(toolbar);
		$("<label class='control-label small'></label>").text(__("Month")).appendTo(month_group);
		const month_input = $("<input type='month' class='form-control input-sm'>")
			.val(data.period?.month || get_state(frm).month)
			.appendTo(month_group);
		month_input.on("change", () => {
			if (month_input.val()) load_overview(frm, month_input.val());
		});

		const actions = $("<div class='wt-project-overview__actions'></div>").appendTo(toolbar);
		const work_actions = $("<div class='wt-project-overview__action-group'></div>").appendTo(actions);
		const create_actions = $("<div class='wt-project-overview__action-group'></div>").appendTo(actions);
		if (data.capabilities?.can_book_time) {
			add_action(work_actions, __("Book time"), async () => {
				if (typeof window.working_time?.open_time_booking_dialog !== "function") {
					throw new Error(__("The time booking dialog is not available."));
				}
				await window.working_time.open_time_booking_dialog({
					project: frm.doc.name,
					on_booked: () => load_overview(frm, get_state(frm).month),
				});
			}, true);
			add_action(work_actions, __("Daily close"), () => open_daily_record());
		}
		if (can_create("Issue")) {
			add_action(create_actions, __("New issue"), () =>
				frappe.new_doc("Issue", { project: frm.doc.name, customer: data.project?.customer })
			);
		}
		if (can_create("Task")) {
			add_action(create_actions, __("New task"), () =>
				frappe.new_doc("Task", { project: frm.doc.name })
			);
		}
		if (data.capabilities?.can_view_purchases && can_create("Purchase Invoice")) {
			add_action(create_actions, __("Purchase invoice"), () =>
				frappe.new_doc("Purchase Invoice", { project: frm.doc.name })
			);
		}
		if (data.project?.customer && can_create("Sales Invoice")) {
			add_action(create_actions, __("Sales invoice"), () =>
				frappe.new_doc("Sales Invoice", {
					customer: data.project.customer,
					project: frm.doc.name,
				})
			);
		}
		if (
			data.capabilities?.can_create_billing_review &&
			data.project?.time_billable &&
			Number(data.project?.billing_rate || 0) > 0 &&
			Number(data.summary?.unbilled_hours || 0) > 0
		) {
			add_action(work_actions, __("Create time invoice draft"), () =>
				create_time_invoice_draft(frm, data)
			);
		}
		if (!work_actions.children().length) work_actions.remove();
		if (!create_actions.children().length) create_actions.remove();
	}

	function add_action(container, label, action, primary = false) {
		const button = $("<button type='button'></button>")
			.addClass(primary ? "btn btn-primary btn-sm" : "btn btn-default btn-sm")
			.text(label)
			.appendTo(container);
		button.on("click", () => run_locked(button, action));
		return button;
	}

	async function run_locked(button, action) {
		if (button.data("working-time-busy")) return;
		button.data("working-time-busy", true).prop("disabled", true).attr("aria-busy", "true");
		try {
			await action();
		} catch (error) {
			frappe.msgprint({
				title: __("Project account"),
				message: window.working_time.safe_error(
					error,
					__("The action could not be completed.")
				),
				indicator: "red",
			});
		} finally {
			button.data("working-time-busy", false).prop("disabled", false).removeAttr("aria-busy");
		}
	}

	async function open_daily_record() {
		const result =
			(await new Promise((resolve, reject) => {
				frappe.xcall("working_time.issues.get_or_create_my_working_time", {
					date: frappe.datetime.get_today(),
				}, "POST", {
					error_handlers: {
						// Frappe's native handler can leave xcall pending. Reject this
						// action so run_locked releases the button for an explicit retry.
						QueryDeadlockError: () => reject(new Error(__(
							"A concurrent request interrupted opening the daily close. Please try again."
						))),
					},
				}).then(resolve, reject);
			})) || {};
		const name = result.working_time || result.name;
		if (name) {
			frappe.set_route("Form", "Working Time", name);
			return;
		}
		if (result.route) {
			window.location.href = result.route;
			return;
		}
		throw new Error(__("No daily working time record is available."));
	}

	async function create_time_invoice_draft(frm, data) {
		const confirmed = await new Promise((resolve) => {
			frappe.confirm(
				__(
					"Create one draft Sales Invoice for the unbilled submitted time? Nothing will be submitted or sent."
				),
				() => resolve(true),
				() => resolve(false)
			);
		});
		if (!confirmed) return;
		const result = await frappe.xcall(
			"working_time.platform_operations.create_project_time_invoice_draft",
			{
				period_start: data.period?.start,
				period_end: data.period?.end,
				project: frm.doc.name,
			}
		);
		const invoices = Array.isArray(result?.sales_invoices) ? result.sales_invoices : [];
		if (invoices.length !== 1) throw new Error(__("No time invoice draft was created."));
		frappe.show_alert({ message: __("Time invoice draft created"), indicator: "green" });
		frappe.set_route("Form", "Sales Invoice", invoices[0]);
	}

	function render_kpis(root, data) {
		const summary = data.summary || {};
		const currency = data.project?.currency;
		const capabilities = data.capabilities || {};
		const kpis = [
			{
				label: __("Hours"),
				value: format_hours(summary.hours),
				detail: __("{0} billable", [format_hours(summary.billable_hours)]),
			},
			{
				label: __("Unbilled"),
				value: format_currency_value(summary.unbilled_amount, currency),
				detail: format_hours(summary.unbilled_hours),
			},
			{
				label: __("Purchases"),
				value: capabilities.can_view_purchases
					? format_currency_value(summary.purchase_cost, currency)
					: "—",
				detail: capabilities.can_view_purchases ? __("Purchase cost") : __("No access"),
			},
			{
				label: __("Invoiced"),
				value: capabilities.can_view_sales
					? format_currency_value(summary.sales_invoiced, currency)
					: "—",
				detail: capabilities.can_view_sales
					? __("{0} in drafts", [format_currency_value(summary.sales_draft, currency)])
					: __("No access"),
			},
			{
				label: __("Margin"),
				value:
					capabilities.can_view_purchases && capabilities.can_view_sales
						? format_currency_value(summary.margin, currency)
						: "—",
				detail: __("{0} time cost", [format_currency_value(summary.time_cost, currency)]),
			},
		];
		const grid = $("<div class='wt-project-overview__kpis'></div>").appendTo(root);
		for (const kpi of kpis) {
			const card = $("<div class='wt-project-overview__kpi'></div>").appendTo(grid);
			$("<div class='text-muted small'></div>").text(kpi.label).appendTo(card);
			$("<div class='wt-project-overview__kpi-value'></div>").text(kpi.value).appendTo(card);
			$("<div class='text-muted small'></div>").text(kpi.detail).appendTo(card);
		}
	}

	function render_time_table(root, rows, currency) {
		const section = create_section(root, __("Time entries"), rows.length);
		if (!rows.length) return render_empty(section);
		const table = create_table(section, [
			__("Date"),
			__("Employee"),
			__("Reference"),
			__("Description"),
			__("Hours"),
			__("Unbilled"),
		]);
		for (const row of rows) {
			const tr = $("<tr></tr>").appendTo(table.find("tbody"));
			append_cell(tr, record_link("Timesheet", row.timesheet, format_date(row.date)), "text-nowrap");
			append_cell(tr, row.employee_name || row.employee || "");
			const relation = $("<div class='wt-project-overview__relation'></div>");
			if (row.task) relation.append(record_link("Task", row.task, row.task));
			if (row.issue) relation.append(record_link("Issue", row.issue, row.issue));
			if (!row.task && !row.issue) relation.text(row.activity_type || "—");
			append_cell(tr, relation);
			append_cell(tr, plain_text(row.description) || "—", "wt-project-overview__description");
			append_cell(tr, format_hours(row.hours), "text-right text-nowrap");
			if (row.sales_invoice) {
				append_cell(
					tr,
					record_link("Sales Invoice", row.sales_invoice, row.sales_invoice),
					"text-right text-nowrap"
				);
			} else {
				append_cell(
					tr,
					format_currency_value(row.unbilled_amount, currency),
					"text-right text-nowrap"
				);
			}
		}
	}

	function render_invoice_table({
		root,
		title,
		doctype,
		rows,
		count,
		party_key,
		party_fallback,
		currency,
	}) {
		const section = create_section(root, title, Number(count ?? rows.length));
		if (!rows.length) return render_empty(section);
		const table = create_table(section, [
			__("Date"),
			__("Document"),
			__("Party"),
			__("Status"),
			__("Amount"),
		]);
		for (const row of rows) {
			const tr = $("<tr></tr>").appendTo(table.find("tbody"));
			append_cell(tr, format_date(row.posting_date), "text-nowrap");
			append_cell(tr, record_link(doctype, row.name, row.name));
			append_cell(tr, row[party_key] || row[party_fallback] || "—");
			append_cell(tr, row.status ? __(String(row.status)) : "—");
			append_cell(tr, format_currency_value(row.amount, currency), "text-right text-nowrap");
		}
	}

	function create_section(root, title, count) {
		const section = $("<section class='wt-project-overview__section'></section>").appendTo(root);
		const title_row = $("<div class='wt-project-overview__section-title'></div>").appendTo(section);
		$("<h4></h4>").text(title).appendTo(title_row);
		if (Number(count || 0) > 0) {
			$("<span class='wt-project-overview__count'></span>")
				.text(`(${Number(count)})`)
				.appendTo(title_row);
		}
		return section;
	}

	function create_table(section, headings) {
		const responsive = $("<div class='table-responsive'></div>").appendTo(section);
		const table = $("<table class='table table-bordered table-hover table-sm'></table>").appendTo(
			responsive
		);
		const head = $("<thead><tr></tr></thead>").appendTo(table).find("tr");
		for (const heading of headings) {
			$("<th scope='col'></th>").text(heading).appendTo(head);
		}
		$("<tbody></tbody>").appendTo(table);
		return table;
	}

	function render_empty(section) {
		$("<div class='wt-project-overview__empty text-muted small'></div>")
			.text(__("No entries in this month."))
			.appendTo(section);
	}

	function append_cell(row, value, class_name = "") {
		const cell = $("<td></td>").addClass(class_name).appendTo(row);
		if (value?.jquery) cell.append(value);
		else cell.text(value === undefined || value === null ? "" : String(value));
		return cell;
	}

	function record_link(doctype, name, label) {
		if (!name) return $("<span></span>").text(label || "—");
		return $("<a href='#'></a>")
			.text(label || name)
			.on("click", (event) => {
				event.preventDefault();
				frappe.set_route("Form", doctype, name);
			});
	}

	function plain_text(value) {
		if (!value) return "";
		const document_fragment = new DOMParser().parseFromString(String(value), "text/html");
		return (document_fragment.body.textContent || "").replace(/\s+/g, " ").trim();
	}

	function format_date(value) {
		return value ? frappe.datetime.str_to_user(String(value)) : "—";
	}

	function format_hours(value) {
		const numeric = Number(value || 0);
		return `${numeric.toLocaleString(undefined, { maximumFractionDigits: 2 })} h`;
	}

	function format_currency_value(value, currency) {
		return format_currency(Number(value || 0), currency || undefined);
	}

	function can_create(doctype) {
		return typeof frappe.model?.can_create !== "function" || frappe.model.can_create(doctype);
	}
})();
