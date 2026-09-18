# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, getdate


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart_data(data)
	return columns, data, None, chart


def get_columns():
	return [
		{
			"label": _("Cover"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Employee Health Insurance",
			"width": 200,
		},
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 130,
		},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Enrolment Date"), "fieldname": "enrolment_date", "fieldtype": "Date", "width": 120},
		{"label": _("Valid Upto"), "fieldname": "valid_upto", "fieldtype": "Date", "width": 110},
		{"label": _("Active"), "fieldname": "is_active", "fieldtype": "Check", "width": 80},
		{"label": _("Inpatient"), "fieldname": "inpatient_cover", "fieldtype": "Check", "width": 90},
		{"label": _("Outpatient"), "fieldname": "outpatient_cover", "fieldtype": "Check", "width": 95},
		{"label": _("Catastrophe"), "fieldname": "catastrophe_cover", "fieldtype": "Check", "width": 100},
		{"label": _("Self Deduction"), "fieldname": "self_deduction", "fieldtype": "Currency", "width": 120},
		{
			"label": _("Dependent Deduction"),
			"fieldname": "dependent_deduction",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Employer Contribution"),
			"fieldname": "employer_contribution",
			"fieldtype": "Currency",
			"width": 160,
		},
		{"label": _("Dependents"), "fieldname": "dependent_count", "fieldtype": "Int", "width": 100},
		{
			"label": _("Superseded By"),
			"fieldname": "superseded_by",
			"fieldtype": "Link",
			"options": "Employee Health Insurance",
			"width": 200,
		},
	]


def get_data(filters):
	conditions = ["1=1"]
	values = {}

	if filters.get("employee"):
		conditions.append("ehi.employee = %(employee)s")
		values["employee"] = filters["employee"]

	if filters.get("is_active") in (0, 1, "0", "1"):
		conditions.append("ehi.is_active = %(is_active)s")
		values["is_active"] = cint(filters["is_active"])

	if filters.get("inpatient_cover"):
		conditions.append("ehi.inpatient_cover = 1")
	if filters.get("outpatient_cover"):
		conditions.append("ehi.outpatient_cover = 1")
	if filters.get("catastrophe_cover"):
		conditions.append("ehi.catastrophe_cover = 1")

	if filters.get("from_date"):
		conditions.append("ehi.enrolment_date >= %(from_date)s")
		values["from_date"] = getdate(filters["from_date"])
	if filters.get("to_date"):
		conditions.append("ehi.enrolment_date <= %(to_date)s")
		values["to_date"] = getdate(filters["to_date"])

	where = " AND ".join(conditions)
	return frappe.db.sql(
		f"""
		SELECT
			ehi.name,
			ehi.employee,
			ehi.employee_name,
			ehi.enrolment_date,
			ehi.valid_upto,
			ehi.is_active,
			ehi.inpatient_cover,
			ehi.outpatient_cover,
			ehi.catastrophe_cover,
			ehi.self_deduction,
			ehi.dependent_deduction,
			ehi.employer_contribution,
			ehi.superseded_by,
			(
				SELECT COUNT(*)
				FROM `tabInsurance Dependent` d
				WHERE d.parent = ehi.name
			) AS dependent_count
		FROM `tabEmployee Health Insurance` ehi
		WHERE {where}
		ORDER BY ehi.employee, ehi.enrolment_date DESC, ehi.creation DESC
		""",
		values,
		as_dict=True,
	)


def get_chart_data(data):
	inpatient = sum(1 for row in data if cint(row.inpatient_cover) and cint(row.is_active))
	outpatient = sum(1 for row in data if cint(row.outpatient_cover) and cint(row.is_active))
	catastrophe = sum(1 for row in data if cint(row.catastrophe_cover) and cint(row.is_active))
	return {
		"data": {
			"labels": [_("Inpatient"), _("Outpatient"), _("Catastrophe")],
			"datasets": [{"name": _("Active Covers"), "values": [inpatient, outpatient, catastrophe]}],
		},
		"type": "bar",
	}
