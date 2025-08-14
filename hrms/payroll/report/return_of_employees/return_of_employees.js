// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Return of Employees"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
			width: "100px",
		},
		{
			fieldname: "to_date",
			label: __("To"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
			width: "100px",
		},
		{
			fieldname: "currency",
			fieldtype: "Link",
			options: "Currency",
			label: __("Currency"),
			default: erpnext.get_currency(frappe.defaults.get_default("Company")),
			width: "50px",
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
			width: "100px",
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			width: "100px",
			reqd: 1,
		},
		{
			fieldname: "docstatus",
			label: __("Document Status"),
			fieldtype: "Select",
			options: ["Draft", "Submitted", "Cancelled"],
			default: "Submitted",
			width: "100px",
		},
	],
	onload: function(report) {
		report.page.add_inner_button(__("Export ROE"), function() {
			// Get current filters
			let filters = report.get_values();
			
			// Show loading indicator
			frappe.show_alert({
				message: __("Exporting Return of Employees..."),
				indicator: 'blue'
			});
			
			// Call the server-side function
			frappe.call({
				method: "hrms.payroll.report.return_of_employees.return_of_employees.export_roe",
				args: {
					filters: filters
				},
				callback: function(r) {
					if (r.message) {
						// Handle successful response
						if (r.message.success) {
							frappe.show_alert({
								message: __("Export completed successfully!"),
								indicator: 'green'
							});
							
							// If the function returns a file URL, you can download it
							if (r.message.file_url) {
								window.open(r.message.file_url);
							}
						} else {
							frappe.msgprint(r.message.error || __("Export failed"));
						}
					}
				},
				error: function(r) {
					frappe.msgprint(__("An error occurred during export"));
				}
			});
		});
	}
};

	