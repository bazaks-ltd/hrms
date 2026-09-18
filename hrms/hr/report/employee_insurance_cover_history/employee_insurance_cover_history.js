// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Employee Insurance Cover History"] = {
	filters: [
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "from_date",
			label: __("Enrolment From"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("Enrolment To"),
			fieldtype: "Date",
		},
		{
			fieldname: "is_active",
			label: __("Active"),
			fieldtype: "Select",
			options: "\n1\n0",
		},
		{
			fieldname: "inpatient_cover",
			label: __("Inpatient Cover"),
			fieldtype: "Check",
		},
		{
			fieldname: "outpatient_cover",
			label: __("Outpatient Cover"),
			fieldtype: "Check",
		},
		{
			fieldname: "catastrophe_cover",
			label: __("Catastrophe Cover"),
			fieldtype: "Check",
		},
	],
};
