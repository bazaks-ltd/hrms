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
			fieldname: "has_inpatient_cover",
			label: __("Has Inpatient Cover"),
			fieldtype: "Check",
		},
		{
			fieldname: "has_outpatient_cover",
			label: __("Has Outpatient Cover"),
			fieldtype: "Check",
		},
		{
			fieldname: "has_catastrophe_cover",
			label: __("Has Catastrophe Cover"),
			fieldtype: "Check",
		},
	],
};
