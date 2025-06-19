// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Employee Overtime', {
    onload: function(frm) {
        // Check if we've already reloaded (using URL parameter)
        const urlParams = new URLSearchParams(window.location.search);
        
        if (!urlParams.has('reloaded')) {
            // Add parameter and reload
            const newUrl = window.location.href + (window.location.href.includes('?') ? '&' : '?') + 'reloaded=1';
            window.location.href = newUrl;
            return;
        }
    },

    onload_post_render: function(frm) {
        // Your existing field logic - will work properly after the page refresh
        ['from_time', 'to_time'].forEach(fieldname => {
            let field = frm.fields_dict[fieldname];
            if (field && field.$input) {
                field.$input.on('blur', function() {
                    $(this).data('stored_value', $(this).val());
                });
                
                field.$input.on('focus', function() {
                    let stored_value = $(this).data('stored_value');
                    setTimeout(() => {
                        let current_value = $(this).val();
                        if (stored_value && current_value !== stored_value) {
                            $(this).val(stored_value);
                            $(this).trigger('change');
                        }
                    }, 100);
                });
            }
        });
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
    var from = frm.doc.from_time;
    var to = frm.doc.to_time;
    var date = frm.doc.date; // Assuming there is a date field in the form

    if (from && to && date) {
        var from_datetime = new Date(date + ' ' + from);
        var to_datetime = new Date(date + ' ' + to);

        // If to_time is earlier than from_time, it means the to_time is on the next day
        if (to_datetime < from_datetime) {
            to_datetime.setDate(to_datetime.getDate() + 1);
        }
        
        var hours = (to_datetime - from_datetime) / (1000 * 60 * 60); // Convert milliseconds to hours
        frm.set_value('number_of_hours', hours);
        frm.refresh_field('number_of_hours');
    }
}