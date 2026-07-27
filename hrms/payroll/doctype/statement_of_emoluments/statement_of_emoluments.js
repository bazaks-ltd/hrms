// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Statement of Emoluments", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Calculate Emoluments"), () => {
				frm.events.populate_from_employee(frm, true);
			}).addClass("btn-primary");
		}
	},

	employee(frm) {
		if (!frm.doc.employee) {
			return;
		}
		if (!frm.doc.income_year) {
			const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
			const year = today.getFullYear();
			const month = today.getMonth() + 1;
			// income_year handler will calculate
			frm.set_value("income_year", month >= 7 ? year + 1 : year);
		} else {
			frm.events.populate_from_employee(frm, true);
		}
	},

	income_year(frm) {
		if (!frm.doc.employee || !frm.doc.income_year) {
			return;
		}
		frm.events.populate_from_employee(frm, true);
	},

	populate_from_employee(frm, calculate) {
		return frm
			.call({
				doc: frm.doc,
				method: "populate_from_employee",
				args: {
					calculate_emoluments: calculate ? 1 : 0,
				},
				freeze: true,
				freeze_message: __("Calculating emoluments..."),
			})
			.then(() => {
				frm.refresh_fields();
				frappe.show_alert({
					message: __("Employee details and emoluments updated"),
					indicator: "green",
				});
			});
	},
});
