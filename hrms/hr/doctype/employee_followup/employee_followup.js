// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Employee Followup', {
	refresh: function(frm) {
		// Set status based on followup_completed checkbox
		if (frm.doc.followup_completed) {
			frm.set_value('status', 'Completed');
		}
		
		// Add custom button to mark as completed
		if (frm.doc.docstatus === 1 && !frm.doc.followup_completed) {
			frm.add_custom_button(__('Mark as Completed'), function() {
				frm.set_value('followup_completed', 1);
				frm.set_value('status', 'Completed');
				frm.save();
			});
		}
	},
	
	employee: function(frm) {
		if (frm.doc.employee) {
			frappe.db.get_value('Employee', frm.doc.employee, ['employee_name', 'department', 'designation', 'company', 'date_of_joining'], (r) => {
				if (r) {
					frm.set_value('employee_name', r.employee_name);
					frm.set_value('department', r.department);
					frm.set_value('designation', r.designation);
					frm.set_value('company', r.company);
				}
			});
		}
	},
	
	followup_conducted_by: function(frm) {
		if (frm.doc.followup_conducted_by) {
			frappe.db.get_value('Employee', frm.doc.followup_conducted_by, 'employee_name', (r) => {
				if (r) {
					frm.set_value('followup_conducted_by_name', r.employee_name);
				}
			});
		}
	},
	
	followup_completed: function(frm) {
		if (frm.doc.followup_completed) {
			frm.set_value('status', 'Completed');
		} else if (frm.doc.status === 'Completed') {
			frm.set_value('status', 'In Progress');
		}
	},
	
	followup_date: function(frm) {
		if (frm.doc.followup_date && frm.doc.employee) {
			frappe.db.get_value('Employee', frm.doc.employee, 'date_of_joining', (r) => {
				if (r && r.date_of_joining) {
					if (frm.doc.followup_date < r.date_of_joining) {
						frappe.msgprint(__('Follow-up date cannot be before employee\'s date of joining'));
						frm.set_value('followup_date', '');
					}
				}
			});
		}
	}
});

