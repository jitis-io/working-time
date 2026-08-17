frappe.pages["work-cockpit"].on_page_load = function (wrapper) {
	new WorkCockpit(wrapper);
};

class WorkCockpit {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("My Work"),
			single_column: true,
		});
		this.view = "all";
		this.scope = "mine";
		this.type = "all";
		this.project = "";
		this.priority = "";
		this.search = "";
		this.data = null;
		this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		this.page.add_menu_item(__("Projects"), () => frappe.set_route("List", "Project"));
		this.page.add_menu_item(__("Tickets"), () => frappe.set_route("List", "Issue"));
		this.page.add_menu_item(__("Billing Review"), () => frappe.set_route("List", "Billing Review"));
		this.container = $("<div class='work-cockpit'></div>").appendTo(this.page.main);
		this.load();
	}

	async load() {
		this.container.attr("aria-busy", "true").html(
			`<div class="work-cockpit__loading" role="status">${__("Loading work…")}</div>`
		);
		try {
			this.data = await frappe.xcall("working_time.work_cockpit.get_work_cockpit", {
				view: "all",
				scope: this.scope,
			});
			this.render();
		} catch (error) {
			this.container
				.removeAttr("aria-busy")
				.empty()
				.append(
					$("<div class='work-cockpit__error' role='alert'></div>")
						.append($("<strong></strong>").text(__("My Work could not be loaded.")))
						.append($("<p></p>").text(error.message))
						.append(
							$("<button class='btn btn-default'></button>")
								.text(__("Try again"))
								.on("click", () => this.load())
						)
				);
		}
	}

	render() {
		this.container.removeAttr("aria-busy").empty();
		if (this.data.capabilities?.can_create_task) {
			this.page.set_primary_action(__("New task"), () => this.createTask(), "add");
		} else {
			this.page.clear_primary_action();
		}
		this.renderIntro();
		this.renderNavigation();
		this.renderFilters();
		this.status = $("<div class='sr-only' aria-live='polite'></div>").appendTo(this.container);
		this.workArea = $("<div class='work-cockpit__work-area'></div>").appendTo(this.container);
		if ((this.data.provider_errors || []).length) {
			$("<div class='work-cockpit__provider-warning' role='status'></div>")
				.text(__("An external source is currently unavailable. Your ERPNext work remains usable."))
				.prependTo(this.workArea);
		}
		this.renderWorkArea();
	}

	renderIntro() {
		const intro = $("<section class='work-cockpit__intro'></section>").appendTo(this.container);
		const copy = $("<div></div>").appendTo(intro);
		$("<div class='work-cockpit__eyebrow'></div>").text("JITIS WORK").appendTo(copy);
		$("<h2></h2>").text(__("What needs your attention?")).appendTo(copy);
		$("<p></p>")
			.text(__("Tickets, planned tasks and billable work in one calm overview."))
			.appendTo(copy);
		if (this.data.capabilities?.can_create_task) {
			const actions = $("<div class='work-cockpit__intro-actions'></div>").appendTo(intro);
			$("<button class='btn btn-primary'></button>")
				.text(__("New task"))
				.on("click", () => this.createTask())
				.appendTo(actions);
		}
	}

	viewDefinitions() {
		return [
			{ value: "all", label: __("My work") },
			{ value: "today", label: __("Today") },
			{ value: "unscheduled", label: __("Without date") },
			{ value: "blocked", label: __("Blocked") },
			{ value: "waiting_customer", label: __("Waiting for customer") },
			{ value: "unbilled", label: __("Unbilled") },
		];
	}

	renderNavigation() {
		const nav = $("<nav class='work-cockpit__views' aria-label='Arbeitsansichten'></nav>").appendTo(
			this.container
		);
		for (const definition of this.viewDefinitions()) {
			const count = this.itemsForView(definition.value).length;
			const button = $("<button type='button' class='work-cockpit__view'></button>")
				.attr("aria-pressed", definition.value === this.view ? "true" : "false")
				.toggleClass("is-active", definition.value === this.view)
				.on("click", () => {
					this.view = definition.value;
					this.render();
				});
			$("<span></span>").text(definition.label).appendTo(button);
			$("<span class='work-cockpit__view-count'></span>").text(count).appendTo(button);
			button.appendTo(nav);
		}
	}

	renderFilters() {
		const bar = $("<section class='work-cockpit__filters' aria-label='Filter'></section>").appendTo(
			this.container
		);
		const searchWrap = $("<label class='work-cockpit__search'></label>").appendTo(bar);
		$("<span class='sr-only'></span>").text(__("Search work")).appendTo(searchWrap);
		$("<input type='search' class='form-control'>")
			.attr("placeholder", __("Search title, description, customer or project…"))
			.val(this.search)
			.on("input", (event) => {
				this.search = event.currentTarget.value;
				this.renderWorkArea();
			})
			.appendTo(searchWrap);

		this.addSelectFilter(bar, __("All types"), this.type, [
			["all", __("All types")],
			["Issue", __("Tickets")],
			["Task", __("Tasks")],
			["External", __("GitHub / external")],
		], (value) => {
			this.type = value;
			this.renderWorkArea();
		});

		const projects = [
			...new Set(
				(this.data.items || [])
					.map((item) => (item.project ? String(item.project) : ""))
					.filter(Boolean)
			),
		].sort((a, b) => a.localeCompare(b));
		if (this.project && !projects.includes(this.project)) this.project = "";
		this.addSelectFilter(
			bar,
			__("All projects"),
			this.project,
			[["", __("All projects")], ...projects.map((project) => [project, project])],
			(value) => {
				this.project = value;
				this.renderWorkArea();
			}
		);

		this.addSelectFilter(bar, __("All priorities"), this.priority, [
			["", __("All priorities")],
			["Urgent", __("Urgent")],
			["High", __("High")],
			["Medium", __("Medium")],
			["Low", __("Low")],
		], (value) => {
			this.priority = value;
			this.renderWorkArea();
		});

		if (this.data.can_view_team) {
			const scope = $("<div class='work-cockpit__scope' role='group'></div>").appendTo(bar);
			for (const definition of [
				["mine", __("Mine")],
				["team", __("Team")],
			]) {
				$("<button type='button'></button>")
					.text(definition[1])
					.toggleClass("is-active", definition[0] === this.scope)
					.attr("aria-pressed", definition[0] === this.scope ? "true" : "false")
					.on("click", () => {
						if (this.scope === definition[0]) return;
						this.scope = definition[0];
						this.project = "";
						this.load();
					})
					.appendTo(scope);
			}
		}
	}

	addSelectFilter(container, label, value, options, onChange) {
		const wrapper = $("<label class='work-cockpit__select'></label>").appendTo(container);
		$("<span class='sr-only'></span>").text(label).appendTo(wrapper);
		const select = $("<select class='form-control'></select>").val(value).appendTo(wrapper);
		for (const [optionValue, optionLabel] of options) {
			$("<option></option>").attr("value", optionValue).text(optionLabel).appendTo(select);
		}
		select.val(value).on("change", (event) => onChange(event.currentTarget.value));
	}

	itemsForView(view) {
		const today = frappe.datetime.get_today();
		return (this.data?.items || []).filter((item) => {
			if (view === "all") return true;
			if (view === "blocked") return item.operational_state === "Blockiert";
			if (view === "waiting_customer") return item.operational_state === "Wartet auf Kunde";
			if (view === "unbilled") return Boolean(item.unbilled);
			if (view === "unscheduled") {
				return !item.due_date && !item.worked_today && item.status !== "Working";
			}
			return (
				item.worked_today ||
				item.status === "Working" ||
				(Boolean(item.due_date) && item.due_date <= today)
			);
		});
	}

	filteredItems() {
		const words = this.search
			.trim()
			.toLocaleLowerCase()
			.split(/\s+/)
			.filter(Boolean);
		const priorities = { Urgent: 0, High: 1, Medium: 2, Low: 3 };
		return this.itemsForView(this.view)
			.filter((item) => this.type === "all" || item.item_type === this.type)
			.filter((item) => !this.project || item.project === this.project)
			.filter((item) => !this.priority || item.priority === this.priority)
			.filter((item) => {
				const haystack = [
					item.title,
					item.name,
					this.plainText(item.description, item.description_is_plain_text),
					item.customer,
					item.project_name,
					item.project,
				]
					.filter(Boolean)
					.join(" ")
					.toLocaleLowerCase();
				return words.every((word) => haystack.includes(word));
			})
			.sort((left, right) => {
				const leftDate = left.due_date || "9999-12-31";
				const rightDate = right.due_date || "9999-12-31";
				return (
					leftDate.localeCompare(rightDate) ||
					(priorities[left.priority] ?? 9) - (priorities[right.priority] ?? 9) ||
					left.title.localeCompare(right.title)
				);
			});
	}

	renderWorkArea() {
		if (!this.workArea) return;
		this.workArea.find(".work-cockpit__results").remove();
		const results = $("<div class='work-cockpit__results'></div>").appendTo(this.workArea);
		const items = this.filteredItems();
		this.status?.text(__("{0} work items shown", [items.length]));
		$("<div class='work-cockpit__result-count'></div>")
			.text(__("{0} entries", [items.length]))
			.appendTo(results);
		if (!items.length) {
			const empty = $("<div class='work-cockpit__empty'></div>").appendTo(results);
			$("<div class='work-cockpit__empty-mark'>✓</div>").appendTo(empty);
			$("<h3></h3>").text(__("Nothing is waiting here.")).appendTo(empty);
			$("<p></p>")
				.text(__("Change the filters or capture the next task directly."))
				.appendTo(empty);
			if (this.data.capabilities?.can_create_task) {
				$("<button class='btn btn-primary'></button>")
					.text(__("New task"))
					.on("click", () => this.createTask())
					.appendTo(empty);
			}
			return;
		}
		for (const group of this.groupItems(items)) {
			const section = $("<section class='work-cockpit__group'></section>").appendTo(results);
			const heading = $("<div class='work-cockpit__group-heading'></div>").appendTo(section);
			$("<h3></h3>").text(group.label).appendTo(heading);
			$("<span></span>").text(group.items.length).appendTo(heading);
			const list = $("<div class='work-cockpit__list' role='list'></div>").appendTo(section);
			for (const item of group.items) this.renderItem(item).appendTo(list);
		}
	}

	groupItems(items) {
		const today = frappe.datetime.get_today();
		const groups = {
			overdue: { label: __("Overdue"), items: [] },
			today: { label: __("Today"), items: [] },
			upcoming: { label: __("Upcoming"), items: [] },
			unscheduled: { label: __("Without date"), items: [] },
		};
		for (const item of items) {
			if (item.due_date && item.due_date < today) groups.overdue.items.push(item);
			else if (item.due_date === today || item.status === "Working" || item.worked_today) {
				groups.today.items.push(item);
			} else if (item.due_date) groups.upcoming.items.push(item);
			else groups.unscheduled.items.push(item);
		}
		return Object.values(groups).filter((group) => group.items.length);
	}

	renderItem(item) {
		const row = $("<article class='work-cockpit__item' role='listitem'></article>");
		row.addClass(`is-${item.item_type.toLowerCase()}`);
		const body = $("<div class='work-cockpit__item-body'></div>").appendTo(row);
		const titleRow = $("<div class='work-cockpit__item-title-row'></div>").appendTo(body);
		$("<span class='work-cockpit__type'></span>").text(this.typeLabel(item)).appendTo(titleRow);
		const title = $("<a class='work-cockpit__item-title'></a>").text(item.title).appendTo(titleRow);
		this.applyRoute(title, item.route);
		if (["Urgent", "High"].includes(item.priority)) {
			$("<span class='work-cockpit__pill is-priority'></span>")
				.text(__(item.priority))
				.appendTo(titleRow);
		}
		if (item.operational_state && item.operational_state !== "Normal") {
			$("<span class='work-cockpit__pill is-state'></span>")
				.text(__(item.operational_state))
				.appendTo(titleRow);
		}

		const description = this.plainText(item.description, item.description_is_plain_text);
		if (description) {
			$("<p class='work-cockpit__description'></p>").text(description).appendTo(body);
		}
		const meta = $("<div class='work-cockpit__meta'></div>").appendTo(body);
		this.addMeta(meta, item.project_name || item.project, "project");
		this.addMeta(meta, item.customer, "customer");
		this.addMeta(meta, item.issue ? __("Ticket {0}", [item.issue]) : "", "issue");
		this.addMeta(meta, this.dueLabel(item), this.isOverdue(item) ? "overdue" : "date");
		this.addMeta(meta, this.assignmentLabel(item), "assignee");
		if (Number(item.actual_hours) > 0) {
			this.addMeta(meta, __("{0} h booked", [flt(item.actual_hours, 2)]), "hours");
		}
		for (const status of item.billing_statuses || []) {
			this.addMeta(meta, __(status), "billing");
		}

		const actions = $("<div class='work-cockpit__item-actions'></div>").appendTo(row);
		if (
			this.data.capabilities?.can_book_time &&
			(item.item_type === "Issue" || (item.item_type === "Task" && item.project))
		) {
			$("<button class='btn btn-sm btn-default'></button>")
				.text(__("Book time"))
				.on("click", () => this.bookTime(item))
				.appendTo(actions);
		}
		if (item.can_promote && this.data.capabilities?.can_create_task) {
			$("<button class='btn btn-sm btn-default'></button>")
				.text(__("Plan as task"))
				.on("click", () => this.promote(item))
				.appendTo(actions);
		}
		if (item.item_type === "Task" && this.data.capabilities?.can_update_task) {
			$("<button class='btn btn-sm btn-default work-cockpit__complete'></button>")
				.text(__("Complete"))
				.on("click", () => this.complete(item))
				.appendTo(actions);
		}
		const open = $("<a class='btn btn-sm btn-default work-cockpit__open'></a>")
			.attr("aria-label", __("Open {0}", [item.title]))
			.text("→")
			.appendTo(actions);
		this.applyRoute(open, item.route);
		return row;
	}

	addMeta(container, value, kind) {
		if (!value) return;
		$("<span></span>").addClass(`is-${kind}`).text(value).appendTo(container);
	}

	typeLabel(item) {
		if (item.item_type === "Issue") return __("Ticket");
		if (item.item_type === "Task") return __("Task");
		return item.source === "github" ? "GitHub" : __("External");
	}

	plainText(value, alreadyPlain = false) {
		if (!value) return "";
		if (alreadyPlain) return String(value).replace(/\s+/g, " ").trim();
		const document = new DOMParser().parseFromString(String(value), "text/html");
		return (document.body.textContent || "").replace(/\s+/g, " ").trim();
	}

	isOverdue(item) {
		return Boolean(item.due_date && item.due_date < frappe.datetime.get_today());
	}

	dueLabel(item) {
		if (!item.due_date) return "";
		const date = frappe.datetime.str_to_user(item.due_date);
		return this.isOverdue(item) ? __("Overdue: {0}", [date]) : date;
	}

	assignmentLabel(item) {
		const users = item.assigned_to || [];
		if (!users.length) return __("Unassigned");
		if (users.length === 1) return users[0];
		return __("{0} assignees", [users.length]);
	}

	applyRoute(element, route) {
		if (!route) {
			element.replaceWith($("<span></span>").addClass(element.attr("class")).text(element.text()));
			return;
		}
		element.attr("href", route);
		if (/^https:\/\//.test(route)) element.attr({ target: "_blank", rel: "noopener noreferrer" });
	}

	bookTime(item) {
		const key = item.item_type === "Task" ? "task" : "issue";
		window.location.href = `/app/working-time-quick-entry?${key}=${encodeURIComponent(item.name)}`;
	}

	async createTask() {
		let context;
		try {
			context = await frappe.xcall("working_time.work_cockpit.get_quick_task_context");
		} catch (error) {
			frappe.msgprint({ title: __("New task"), message: error.message, indicator: "red" });
			return;
		}
		if (!(context.projects || []).length) {
			frappe.msgprint({
				title: __("New task"),
				message: __("Create or reopen a project before adding tasks."),
				indicator: "orange",
			});
			return;
		}
		let submitting = false;
		const dialog = new frappe.ui.Dialog({
			title: __("New task"),
			fields: [
				{ fieldname: "subject", fieldtype: "Data", label: __("Title"), reqd: 1 },
				{
					fieldname: "project",
					fieldtype: "Link",
					options: "Project",
					label: __("Project"),
					reqd: 1,
					default: context.default_project,
					get_query: () => ({ filters: { status: "Open" } }),
				},
				{ fieldname: "description", fieldtype: "Small Text", label: __("Description") },
				{ fieldname: "due_date", fieldtype: "Date", label: __("Due date") },
				{
					fieldname: "priority",
					fieldtype: "Select",
					label: __("Priority"),
					options: ["Low", "Medium", "High", "Urgent"],
					default: "Medium",
				},
			],
			primary_action_label: __("Create task"),
			primary_action: async (values) => {
				if (submitting) return;
				submitting = true;
				dialog.get_primary_btn().prop("disabled", true);
				try {
					const result = await frappe.xcall("working_time.work_cockpit.create_quick_task", values);
					dialog.hide();
					frappe.show_alert({ message: __("Task created"), indicator: "green" });
					await this.load();
					if (result.route) this.lastCreatedRoute = result.route;
				} catch (error) {
					frappe.msgprint({ title: __("New task"), message: error.message, indicator: "red" });
				} finally {
					submitting = false;
					dialog.get_primary_btn().prop("disabled", false);
				}
			},
		});
		dialog.show();
	}

	complete(item) {
		const safeTitle = frappe.utils.escape_html(String(item.title || ""));
		frappe.confirm(__("Mark “{0}” as completed?", [safeTitle]), async () => {
			await frappe.xcall("working_time.work_cockpit.complete_task", { task: item.name });
			frappe.show_alert({ message: __("Task completed"), indicator: "green" });
			await this.load();
		});
	}

	async promote(item) {
		if (item.item_type === "External" && item.promotion_method) {
			const result = await frappe.xcall(item.promotion_method, item.promotion_args || {});
			if (result.route) window.location.href = result.route;
			else await this.load();
			return;
		}
		const context = await frappe.xcall("working_time.work_cockpit.get_issue_promotion_context", {
			issue: item.name,
		});
		if (context.project) return this.runIssuePromotion(item.name, context.project);
		const dialog = new frappe.ui.Dialog({
			title: __("Plan ticket as task"),
			fields: [
				{
					fieldname: "project",
					fieldtype: "Select",
					label: __("Project"),
					options: (context.projects || []).map((project) => project.name).join("\n"),
					reqd: 1,
				},
			],
			primary_action_label: __("Create task"),
			primary_action: async (values) => {
				dialog.hide();
				await this.runIssuePromotion(item.name, values.project);
			},
		});
		dialog.show();
	}

	async runIssuePromotion(issue, project) {
		const result = await frappe.xcall("working_time.work_cockpit.promote_issue_to_task", {
			issue,
			project,
		});
		window.location.href = result.route;
	}
}
