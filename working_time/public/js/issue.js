frappe.ui.form.on("Issue", {
	refresh(frm) {
		if (frm.is_new()) return;
		let opening = false;
		const button = frm.add_custom_button(__("Book time"), async () => {
			if (opening) return;
			opening = true;
			button.prop("disabled", true).attr("aria-busy", "true");
			try {
				if (typeof window.working_time?.open_time_booking_dialog !== "function") {
					throw new Error(__("The time booking dialog is not available."));
				}
				await window.working_time.open_time_booking_dialog({
					project: frm.doc.project || undefined,
					issue: frm.doc.name,
					on_booked: () => frm.reload_doc(),
				});
			} catch (error) {
				frappe.msgprint({
					title: __("Book time"),
					message: frappe.utils.escape_html(
						String(error?.message || __("Time booking could not be opened."))
					),
					indicator: "red",
				});
			} finally {
				opening = false;
				button.prop("disabled", false).removeAttr("aria-busy");
			}
		});
	},
});
