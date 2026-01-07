// Client Script for Salary History DocType
frappe.ui.form.on('Salary History', {
    employee: function(frm) {
        if (frm.doc.employee) {
            // Fetch previous basic salary using server method
            frappe.call({
                method: 'hrms.payroll.doctype.salary_history.salary_history.get_employee_basic_salary',
                args: {
                    employee: frm.doc.employee
                },
                callback: function(r) {
                    if (r.message !== undefined) {
                        frm.set_value('previous_basic_salary', r.message);
                    }
                }
            });
        } else {
            frm.set_value('previous_basic_salary', 0);
        }
    },
    
    change_amount: function(frm) {
        calculate_new_salary(frm);
    },
    
    previous_basic_salary: function(frm) {
        calculate_new_salary(frm);
    }
});

function calculate_new_salary(frm) {
    if (frm.doc.previous_basic_salary && frm.doc.change_amount !== undefined) {
        let new_salary = frm.doc.previous_basic_salary + frm.doc.change_amount;
        frm.set_value('new_basic_salary', new_salary);
        
        if (frm.doc.previous_basic_salary > 0) {
            let change_percentage = (frm.doc.change_amount / frm.doc.previous_basic_salary) * 100;
            frm.set_value('change_percentage', change_percentage);
        }
    }
}