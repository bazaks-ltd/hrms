// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Employee Leave Balance"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
		},
		{
			label: __("Company"),
			fieldname: "company",
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "employee_status",
			label: __("Employee Status"),
			fieldtype: "Select",
			options: [
				"",
				{ value: "Active", label: __("Active") },
				{ value: "Inactive", label: __("Inactive") },
				{ value: "Suspended", label: __("Suspended") },
				{ value: "Left", label: __("Left", null, "Employee") },
			],
			default: "Active",
		},
		{
			fieldname: "consolidate_leave_types",
			label: __("Consolidate Leave Types"),
			fieldtype: "Check",
			default: 1,
			depends_on: "eval: !doc.employee",
		},
	],
	onload: function (report) {
		const today = frappe.datetime.now_date();

		frappe.call({
			type: "GET",
			method: "hrms.hr.utils.get_leave_period",
			args: {
				from_date: today,
				to_date: today,
				company: frappe.defaults.get_user_default("Company"),
			},
			freeze: true,
			callback: (data) => {
				frappe.query_report.set_filter_value("from_date", data.message[0].from_date);
				frappe.query_report.set_filter_value("to_date", data.message[0].to_date);
			},
		});

		// Add Express Report button for Administrator, System Manager, and HR Manager roles
		if (frappe.user.has_role(["Administrator", "System Manager", "HR Manager"])) {
			// Add the generate_express_report method to the report object
			report.generate_express_report = function () {
				let mandatory = this.filters.filter((f) => f.df.reqd);
				let missing_mandatory = mandatory.filter((f) => !f.get_value());
				if (missing_mandatory.length) {
					frappe.msgprint(__("Please set all mandatory filters"));
					return;
				}

				let filters = this.get_filter_values(true);
				
				// Show loading indicator
				frappe.show_progress(__("Generating Express Report"), 0, 100);
				
				frappe.call({
					method: "frappe.core.doctype.prepared_report.prepared_report.generate_express_report",
					args: {
						report_name: this.report_name,
						filters: filters,
					},
					callback: (r) => {
						frappe.hide_progress();
						if (r.message) {
							const data = r.message;
							// Set the prepared report name and refresh
							this.prepared_report_doc_name = data.name;
							this.prepared_report_name = data.name;
							// Refresh the report to show the generated data
							this.refresh();
							frappe.show_alert({
								message: __("Express Report generated successfully"),
								indicator: "green",
							}, 5);
						}
					},
					error: (r) => {
						frappe.hide_progress();
						frappe.msgprint({
							title: __("Error"),
							message: r.message || __("Failed to generate express report"),
							indicator: "red",
						});
					},
				});
			};
			
			report.page.add_inner_button(
				__("Express Report"),
				function () {
					report.generate_express_report();
				},
				__("Actions")
			);
		}
	},
};
