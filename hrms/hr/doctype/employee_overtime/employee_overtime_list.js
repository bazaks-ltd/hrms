frappe.listview_settings['Employee Overtime'] = {
    onload: function(listview) {
        // Add migration button to list view
        listview.page.add_button(__('Migrate Dates'), function() {
            
            // Show confirmation dialog
            frappe.confirm(
                'This will update datetime fields in existing overtime records to use the correct date.\n\nThis action cannot be undone.\n\nContinue?',
                function() {                    
                    // Show progress indicator
                    frappe.show_alert({
                        message: __('Migration in progress...'),
                        indicator: 'blue'
                    });
                    
                    // Call server method
                    frappe.call({
                        method: 'hrms.hr.doctype.employee_overtime.employee_overtime.migrate_overtime_dates', // Your server script method name
                        callback: function(response) {
                            if (response.message) {
                                let result = response.message;
                                
                                if (result.status === 'success') {
                                    // Show success message
                                    frappe.show_alert({
                                        message: result.message,
                                        indicator: 'green'
                                    });
                                    
                                    // Show detailed results if there were updates
                                    if (result.updated_count > 0) {
                                        let msg = `<strong>Migration Results:</strong><br>
                                                  • Updated ${result.updated_count} records<br>`;
                                        
                                        if (result.errors && result.errors.length > 0) {
                                            msg += `• ${result.errors.length} errors occurred<br>`;
                                            console.log('Migration errors:', result.errors);
                                        }
                                        
                                        frappe.msgprint({
                                            message: msg,
                                            title: __('Migration Complete'),
                                            indicator: 'green'
                                        });
                                    }
                                    
                                    // Refresh the list view to show updated data
                                    listview.refresh();
                                    
                                } else {
                                    // Show error message
                                    frappe.show_alert({
                                        message: result.message,
                                        indicator: 'red'
                                    });
                                }
                            }
                        },
                        error: function(error) {
                            frappe.show_alert({
                                message: __('Migration failed. Check console for details.'),
                                indicator: 'red'
                            });
                            console.error('Migration error:', error);
                        }
                    });
                },
                function() {
                    // User cancelled
                    frappe.show_alert({
                        message: __('Migration cancelled'),
                        indicator: 'yellow'
                    });
                }
            );
        }).addClass('btn-warning');
    }
};