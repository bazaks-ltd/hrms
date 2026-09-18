# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate


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
		{"label": _("Inpatient Cover"), "fieldname": "inpatient_cover", "fieldtype": "Currency", "width": 130},
		{"label": _("Outpatient Cover"), "fieldname": "outpatient_cover", "fieldtype": "Currency", "width": 140},
		{
			"label": _("Catastrophe Cover"),
			"fieldname": "insurance_catastrophe_cover",
			"fieldtype": "Currency",
			"width": 150,
		},
		{
			"label": _("Dependent Catastrophe Cover"),
			"fieldname": "dependent_catastrophe_cover",
			"fieldtype": "Currency",
			"width": 180,
		},
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

	if filters.get("has_inpatient_cover"):
		conditions.append("IFNULL(ehi.inpatient_cover, 0) > 0")
	if filters.get("has_outpatient_cover"):
		conditions.append("IFNULL(ehi.outpatient_cover, 0) > 0")
	if filters.get("has_catastrophe_cover"):
		conditions.append(
			"(IFNULL(ehi.insurance_catastrophe_cover, 0) > 0 OR IFNULL(ehi.dependent_catastrophe_cover, 0) > 0)"
		)

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
			ehi.insurance_catastrophe_cover,
			ehi.dependent_catastrophe_cover,
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
	inpatient = sum(1 for row in data if flt(row.inpatient_cover) and cint(row.is_active))
	outpatient = sum(1 for row in data if flt(row.outpatient_cover) and cint(row.is_active))
	catastrophe = sum(
		1
		for row in data
		if (flt(row.insurance_catastrophe_cover) or flt(row.dependent_catastrophe_cover))
		and cint(row.is_active)
	)
	return {
		"data": {
			"labels": [_("Inpatient"), _("Outpatient"), _("Catastrophe")],
			"datasets": [{"name": _("Active Covers"), "values": [inpatient, outpatient, catastrophe]}],
		},
		"type": "bar",
	}
