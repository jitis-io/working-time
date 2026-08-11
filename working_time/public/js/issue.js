frappe.ui.form.on("Issue", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Zeit buchen"), () => {
			window.location.href = `/app/working-time-quick-entry?issue=${encodeURIComponent(frm.doc.name)}`;
		});
	},
});
