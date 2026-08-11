frappe.ui.form.on("Task", {
	async refresh(frm) {
		if (frm.is_new() || !frm.doc.issue) return;
		const files = await frappe.xcall("working_time.work_cockpit.get_issue_attachments", {
			task: frm.doc.name,
		});
		const field = "working_time_issue_attachments_html";
		if (!files.length) {
			frm.set_df_property(field, "options", `<p class="text-muted">${__("No private Issue attachments.")}</p>`);
			frm.refresh_field(field);
			return;
		}
		const list = $("<ul class='mb-0'></ul>");
		for (const file of files) {
			let url;
			try {
				url = new URL(file.file_url, window.location.origin);
			} catch {
				continue;
			}
			if (!["http:", "https:"].includes(url.protocol)) continue;
			const link = $("<a target='_blank' rel='noopener noreferrer'></a>")
				.attr("href", url.href)
				.text(file.file_name || file.name);
			$("<li></li>").append(link).appendTo(list);
		}
		frm.set_df_property(field, "options", list.prop("outerHTML"));
		frm.refresh_field(field);
	},
});
