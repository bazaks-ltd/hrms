// bulk_salary_increment.js
frappe.ui.form.on('Bulk Salary Increment', {
    refresh: function(frm) {
        // Ensure status is always Active
        if (!frm.doc.status) {
            frm.set_value('status', 'Active');
        }
        
        // Add custom button to get employees
        if (!frm.doc.docstatus) {
            frm.add_custom_button(__('Get Employees'), function() {
                frm.call('get_employees').then(() => {
                    frm.refresh_field('employees');
                });
            }).addClass('btn-primary');
            
            // Show message that Salary History will be created on submit
            if (frm.doc.employees && frm.doc.employees.length > 0) {
                frm.dashboard.add_indicator(
                    __('Salary History records will be created automatically when this document is submitted'),
                    'blue'
                );
            }
        }
    },
    
    increment_type: function(frm) {
        // Update field description based on increment type
        if (frm.doc.increment_type === 'Fixed Amount') {
            frm.set_df_property('increment_value', 'description',
                __('Enter fixed amount to add to each employee\'s salary (e.g., 5000)'));
        } else {
            frm.set_df_property('increment_value', 'description',
                __('Enter percentage increase (e.g., 10.5 for 10.5%)'));
        }
        
        // Recalculate if employees are already loaded
        if (frm.doc.employees && frm.doc.employees.length > 0) {
            frm.call('calculate_increments').then(() => {
                frm.refresh_field('employees');
            });
        }
    },
    
    increment_value: function(frm) {
        // Recalculate if employees are already loaded
        if (frm.doc.employees && frm.doc.employees.length > 0) {
            frm.call('calculate_increments').then(() => {
                frm.refresh_field('employees');
            });
        }
    },
    
    get_employees_btn: function(frm) {
        frm.call('get_employees').then(() => {
            frm.refresh_field('employees');
        });
    },
    
    status: function(frm) {
        // Ensure status is always Active
        if (frm.doc.status !== 'Active') {
            frm.set_value('status', 'Active');
            frappe.msgprint(__('Only Active employees can be included in bulk salary increments'));
        }
    }
});

// Handle child table changes
frappe.ui.form.on('Bulk Salary Increment Employee', {
    current_basic_salary: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.current_basic_salary && frm.doc.increment_type && frm.doc.increment_value) {
            let current_salary = flt(row.current_basic_salary);
            let increment_value = flt(frm.doc.increment_value);
            
            let increment_amount, new_salary, increment_percentage;
            
            if (frm.doc.increment_type === 'Fixed Amount') {
                increment_amount = increment_value;
                new_salary = current_salary + increment_amount;
                increment_percentage = current_salary > 0 ? (increment_amount / current_salary * 100) : 0;
            } else {
                increment_percentage = increment_value;
                increment_amount = current_salary * (increment_percentage / 100);
                new_salary = current_salary + increment_amount;
            }
            
            frappe.model.set_value(cdt, cdn, 'increment_amount', increment_amount);
            frappe.model.set_value(cdt, cdn, 'new_basic_salary', new_salary);
            frappe.model.set_value(cdt, cdn, 'increment_percentage', increment_percentage);
        }
    }
});
