// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("MO Leave Policy Assignment", {
	onload: function (frm) {
		frm.ignore_doctypes_on_cancel_all = ["Leave Ledger Entry"];
	},

	employee: function (frm) {
		if (frm.doc.employee) {
			frm.events.set_effective_date(frm);
		}
	},

	set_effective_date: function (frm) {
		if (frm.doc.assignment_based_on == "Joining Date" && frm.doc.employee) {
			frappe.model.with_doc("Employee", frm.doc.employee, function () {
				let date_of_joining = frappe.model.get_value(
					"Employee",
					frm.doc.employee,
					"date_of_joining",
				);
				if (date_of_joining) {
					frm.set_value("effective_from", date_of_joining);
					frm.set_value(
						"effective_to",
						frappe.datetime.add_months(date_of_joining, 12),
					);
				}
			});
		}
		frm.refresh();
	},
});
