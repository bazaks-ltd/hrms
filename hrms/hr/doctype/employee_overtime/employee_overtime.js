// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Employee Overtime', {
    refresh: function(frm) {
        // Clear ALL stored data on every refresh to prevent cross-form contamination
        ['from_time', 'to_time'].forEach(fieldname => {
            let field = frm.fields_dict[fieldname];
            if (field && field.$input) {
                field.$input.removeData();  // Remove all data attributes
            }
        });
    },

    onload_post_render: function(frm) {
        ['from_time', 'to_time'].forEach(fieldname => {
            let field = frm.fields_dict[fieldname];
            if (field && field.$input) {
                // Create a unique session ID for this form instance
                let session_id = Date.now() + '_' + Math.random();
                let initial_value = field.$input.val();
                
                // Store session-specific data
                field.$input.data('session_id', session_id);
                field.$input.data('initial_value', initial_value);
                field.$input.data('has_user_input', false);
                
                field.$input.on('blur', function() {
                    let current_session = $(this).data('session_id');
                    if (current_session === session_id) {  // Only if same session
                        $(this).data('stored_value', $(this).val());
                        $(this).data('has_user_input', true);
                    }
                });
                
                field.$input.on('focus', function() {
                    let current_session = $(this).data('session_id');
                    let has_input = $(this).data('has_user_input');
                    
                    // Only restore if same session AND user had previously input something
                    if (current_session === session_id && has_input) {
                        let stored_value = $(this).data('stored_value');
                        setTimeout(() => {
                            let current_value = $(this).val();
                            if (stored_value && current_value !== stored_value) {
                                $(this).val(stored_value);
                                $(this).trigger('change');
                            }
                        }, 100);
                    }
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