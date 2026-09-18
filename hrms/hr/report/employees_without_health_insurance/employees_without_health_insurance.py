# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 140,
		},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 200},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": 160,
		},
		{
			"label": _("Designation"),
			"fieldname": "designation",
			"fieldtype": "Link",
			"options": "Designation",
			"width": 150,
		},
		{"label": _("Date of Joining"), "fieldname": "date_of_joining", "fieldtype": "Date", "width": 130},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 160,
		},
	]


def get_data(filters):
	conditions = ["e.status = 'Active'", "ehi.name IS NULL"]
	values = {}

	if filters.get("company"):
		conditions.append("e.company = %(company)s")
		values["company"] = filters["company"]
	if filters.get("department"):
		conditions.append("e.department = %(department)s")
		values["department"] = filters["department"]

	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT
			e.name AS employee,
			e.employee_name,
			e.department,
			e.designation,
			e.date_of_joining,
			e.company
		FROM `tabEmployee` e
		LEFT JOIN `tabEmployee Health Insurance` ehi
			ON ehi.employee = e.name AND ehi.is_active = 1
		WHERE {where}
		ORDER BY e.employee_name
		""",
		values,
		as_dict=True,
	)
