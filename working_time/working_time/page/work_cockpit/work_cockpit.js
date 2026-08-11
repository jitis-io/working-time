frappe.pages["work-cockpit"].on_page_load = function (wrapper) {
	new WorkCockpit(wrapper);
};

class WorkCockpit {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Work Cockpit"),
			single_column: true,
		});
		this.view = "today";
		this.page.set_secondary_action(__("Refresh"), () => this.load(), "refresh");
		this.view_field = this.page.add_field({
			fieldname: "view",
			fieldtype: "Select",
			label: __("View"),
			options: [
				{ label: __("Today"), value: "today" },
				{ label: __("Blockiert"), value: "blocked" },
				{ label: __("Wartet auf Kunde"), value: "waiting_customer" },
				{ label: __("Unbilled"), value: "unbilled" },
				{ label: __("All open"), value: "all" },
			],
			default: this.view,
			change: () => {
				this.view = this.view_field.get_value() || "today";
				this.load();
			},
		});
		this.container = $("<div class='work-cockpit mt-4'></div>").appendTo(this.page.main);
		this.load();
	}

	async load() {
		this.container.html(`<div class="text-muted p-4">${__("Loading…")}</div>`);
		try {
			const result = await frappe.xcall("working_time.work_cockpit.get_work_cockpit", {
				view: this.view,
			});
			this.render(result);
		} catch (error) {
			this.container.empty();
			frappe.msgprint({ title: __("Work Cockpit"), message: error.message, indicator: "red" });
		}
	}

	render(result) {
		this.container.empty();
		const counts = result.counts || {};
		const summary = $("<div class='mb-3 text-muted'></div>")
			.text(
				__("{0} Issues · {1} Tasks · {2} external", [
					counts.issues || 0,
					counts.tasks || 0,
					counts.external || 0,
				])
			)
			.appendTo(this.container);
		if ((result.provider_errors || []).length) {
			$("<div class='alert alert-warning'></div>")
				.text(__("One or more external providers could not be loaded. Native work remains available."))
				.insertAfter(summary);
		}
		if (!(result.items || []).length) {
			$("<div class='frappe-card p-4 text-muted'></div>")
				.text(__("No work items in this view."))
				.appendTo(this.container);
			return;
		}
		const table = $(
			`<div class="frappe-card table-responsive">
				<table class="table table-hover mb-0">
					<thead><tr>
						<th>${__("Type")}</th><th>${__("Work item")}</th><th>${__("Status")}</th>
						<th>${__("Customer / Project")}</th><th>${__("Due")}</th>
						<th class="text-right">${__("Hours")}</th><th></th>
					</tr></thead><tbody></tbody>
				</table>
			</div>`
		).appendTo(this.container);
		const body = table.find("tbody");
		for (const item of result.items) {
			body.append(this.row(item));
		}
	}

	row(item) {
		const row = $("<tr></tr>");
		$("<td></td>").text(item.item_type).appendTo(row);
		const title = $("<td></td>").appendTo(row);
		const link = $("<a></a>").text(item.title).appendTo(title);
		if (item.route) link.attr({ href: item.route, rel: "noopener" });
		else link.replaceWith($("<span></span>").text(item.title));
		if (item.operational_state && item.operational_state !== "Normal") {
			$("<div class='small text-muted'></div>").text(__(item.operational_state)).appendTo(title);
		}
		const status = $("<td></td>").text(item.status || "").appendTo(row);
		if ((item.billing_statuses || []).length) {
			$("<div class='small text-muted'></div>").text(item.billing_statuses.join(", ")).appendTo(status);
		}
		const context = $("<td></td>").appendTo(row);
		$("<div></div>").text(item.customer || "—").appendTo(context);
		$("<div class='small text-muted'></div>").text(item.project || "—").appendTo(context);
		$("<td></td>").text(item.due_date ? frappe.datetime.str_to_user(item.due_date) : "—").appendTo(row);
		$("<td class='text-right'></td>").text(flt(item.actual_hours || 0, 2)).appendTo(row);
		const actions = $("<td class='text-right'></td>").appendTo(row);
		if (item.can_promote) {
			$("<button class='btn btn-xs btn-default'></button>")
				.text(__(item.item_type === "Issue" ? "In Task übernehmen" : "Create Task"))
				.on("click", () => this.promote(item))
				.appendTo(actions);
		}
		return row;
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
		if (context.project) {
			return this.runIssuePromotion(item.name, context.project);
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Issue in Task übernehmen"),
			fields: [
				{
					fieldname: "project",
					fieldtype: "Select",
					label: __("Project"),
					options: (context.projects || []).map((project) => project.name).join("\n"),
					reqd: 1,
				},
			],
			primary_action_label: __("Create Task"),
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
