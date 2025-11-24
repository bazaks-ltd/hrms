// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Employee Overtime', {
    onload_post_render(frm) {
        ["from_time", "to_time"].forEach(fieldname => {
            let field = frm.fields_dict[fieldname];
            if (field && field.$input) {
                // destroy the timepicker widget if already attached
                if (field.$input.data("timepicker")) {
                    field.$input.timepicker("destroy");
                }
                // make it plain text
                field.$input.attr("type", "text");
                field.$input.attr("placeholder", "HH:MM:SS");
            }
        });
    },
    date: function(frm) {
        if (frm.doc.date) {
            // Set from_time and to_time to the selected date at midnight
            let date_str = frm.doc.date;

            // Only update if the fields are empty or on a different date
            if (!frm.doc.from_time || frappe.datetime.str_to_obj(frm.doc.from_time).toDateString() !== frappe.datetime.str_to_obj(date_str).toDateString()) {
                frm.set_value("from_time", date_str + " 00:00:00");
            }

            if (!frm.doc.to_time || frappe.datetime.str_to_obj(frm.doc.to_time).toDateString() !== frappe.datetime.str_to_obj(date_str).toDateString()) {
                frm.set_value("to_time", date_str + " 00:00:00");
            }
        }
    },
    from_time: function(frm) {
        calculate_hours(frm);
    },
    to_time: function(frm) {
        calculate_hours(frm);
    },
    employee: function (frm) {
		frm.trigger("set_overtime_approver");
	},
    set_overtime_approver: function (frm) {
		if (frm.doc.employee) {
			return frappe.call({
				method: "hrms.hr.doctype.employee_overtime.employee_overtime.get_overtime_approver",
				args: {
					employee: frm.doc.employee,
				},
				callback: function (r) {
					if (r && r.message) {
						frm.set_value("overtime_approver", r.message);
					}
				},
			});
		}
	},
});

function calculate_hours(frm) {
    let from = frm.doc.from_time;
    let to = frm.doc.to_time;

    if (from && to) {
        // Frappe stores datetime as ISO string e.g. "2025-09-12 18:30:00"
        let from_dt = frappe.datetime.str_to_obj(from);
        let to_dt = frappe.datetime.str_to_obj(to);

        // Handle overnight (to < from)
        if (to_dt < from_dt) {
            to_dt.setDate(to_dt.getDate() + 1);
        }

        let hours = (to_dt - from_dt) / (1000 * 60 * 60); // ms → hours
        frm.set_value("number_of_hours", hours);
    }
}