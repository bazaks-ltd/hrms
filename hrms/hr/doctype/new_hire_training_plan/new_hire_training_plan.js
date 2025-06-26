// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("New Hire Training Plan", {
	refresh(frm) {
        if (!frm.doc.__islocal) {
                    frm.add_custom_button(__('Update Progress'), function() {
                        frm.call('calculate_progress').then(() => {
                            frm.refresh();
                        });
                    });
                    
                    frm.add_custom_button(__('Send Reminder'), function() {
                        send_training_reminder(frm);
                    });
                    
                    // Add button to create new template from current plan
                    if (frappe.user.has_role('HR Manager') && frm.doc.training_assignments.length > 0) {
                        frm.add_custom_button(__('Save as Template'), function() {
                            save_as_template(frm);
                        }, __('Actions'));
                    }
                    
                    // Add button to mark all as completed (for testing)
                    if (frappe.user.has_role('HR Manager')) {
                        frm.add_custom_button(__('Mark All Complete'), function() {
                            mark_all_assignments_complete(frm);
                        }, __('Actions'));
                    }
        } else {
            // Show template selection for new documents
            if (frm.doc.department) {
                show_template_suggestions(frm);
            }
        }
	},
    employee_name: function(frm) {
        if (frm.doc.employee_name) {
            // Auto-fill department from employee
            frappe.db.get_value('Employee', frm.doc.employee_name, 'department')
                .then(r => {
                    if (r.message && r.message.department) {
                        frm.set_value('department', r.message.department);
                    }
                });
        }
    },
    apply_template_btn: function(frm) {
        if (!frm.doc.training_template) {
            frappe.msgprint(__('Please select a training template first'));
            return;
        }
        
        if (frm.doc.training_assignments.length > 0) {
            frappe.confirm(__('This will replace existing assignments. Continue?'), () => {
                apply_selected_template(frm);
            });
        } else {
            apply_selected_template(frm);
        }
    }
});

function apply_selected_template(frm) {
    console.log("Applying training template:", frm.doc.training_template);
    console.log("Training plan name:", frm.doc.name);
    frappe.call({
        method: "run_doc_method",
        args: {
            method: "apply_training_template",
            dt: "New Hire Training Plan",
            dn: frm.doc.name,
            args: {
              template_name: frm.doc.training_template
            }
        },
        callback: function(r) {
            if (!r.exc) {
                frm.reload_doc();
            }
        }
    });
}