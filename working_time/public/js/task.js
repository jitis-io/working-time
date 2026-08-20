frappe.ui.form.on("Task", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.project || frm.doc.status === "Cancelled") return;
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
					project: frm.doc.project,
					issue: frm.doc.issue || undefined,
					task: frm.doc.name,
					on_booked: () => frm.reload_doc(),
				});
			} catch (error) {
				frappe.msgprint({
					title: __("Book time"),
					message: window.working_time.safe_error(
						error,
						__("Time booking could not be opened.")
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
