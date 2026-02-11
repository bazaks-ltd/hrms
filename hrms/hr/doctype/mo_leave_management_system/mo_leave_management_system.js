frappe.ui.form.on("MO Leave Management System", {
	refresh(frm) {
		frm.disable_save();
		frm.enable_save();
	},
});

