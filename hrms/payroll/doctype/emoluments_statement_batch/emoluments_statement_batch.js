// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

function get_mauritius_fiscal_year(date_str) {
	if (!date_str) {
		return null;
	}
	const d = frappe.datetime.str_to_obj(date_str);
	const year = d.getFullYear();
	const month = d.getMonth() + 1;
	if (month >= 7) {
		return {
			start: `${year}-07-01`,
			end: `${year + 1}-06-30`,
		};
	}
	return {
		start: `${year - 1}-07-01`,
		end: `${year}-06-30`,
	};
}

function normalize_mauritius_fy(frm, source_field) {
	const value = frm.doc[source_field];
	if (!value) {
		return;
	}
	const fy = get_mauritius_fiscal_year(value);
	if (!fy) {
		return;
	}
	if (frm.doc.start_date !== fy.start) {
		frm.set_value("start_date", fy.start);
	}
	if (frm.doc.end_date !== fy.end) {
		frm.set_value("end_date", fy.end);
	}
}

frappe.ui.form.on("Emoluments Statement Batch", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.page.clear_primary_action();
			frm.add_custom_button(__("Get Employees"), function () {
				frm.events.get_employee_details(frm);
			}).toggleClass("btn-primary", !(frm.doc.employees || []).length);
		}

		frm.add_custom_button(__("Print"), function () {
			frm.events.print_doc(frm);
		});

		if (
			(frm.doc.employees || []).length &&
			!frappe.model.has_workflow(frm.doctype) &&
			frm.doc.docstatus != 2
		) {
			if (frm.doc.docstatus == 0 && !frm.is_new()) {
				frm.page.clear_primary_action();
				frm.page.set_primary_action(__("Create Emolument Statements"), () => {
					frm.save("Submit").then(() => {
						frm.page.clear_primary_action();
						frm.refresh();
					});
				});
			} else if (frm.doc.docstatus == 1 && frm.doc.status == "Failed") {
				frm.add_custom_button(__("Create Emolument Statements"), function () {
					frm.events.create_emolument_statements(frm);
				}).addClass("btn-primary");
			}
		}
	},
	start_date(frm) {
		normalize_mauritius_fy(frm, "start_date");
	},
	end_date(frm) {
		normalize_mauritius_fy(frm, "end_date");
	},
	create_emolument_statements: function (frm) {
		frm.call({
			doc: frm.doc,
			method: "run_doc_method",
			args: {
				method: "create_emolument_statements",
				dt: "Emoluments Statement Batch",
				dn: frm.doc.name,
			},
		});
	},
	print_doc: function (frm) {
		return frappe.call({
			doc: frm.doc,
			method: "print_data",
		});
	},
	get_employee_details: function (frm) {
		return frappe
			.call({
				doc: frm.doc,
				method: "fill_employee_details",
				freeze: true,
				freeze_message: __("Fetching Employees"),
			})
			.then((r) => {
				if (r.docs?.[0]?.employees) {
					frm.dirty();
					frm.save();
				}

				frm.refresh();

				frm.scroll_to_field("employees");
			});
	},
});
