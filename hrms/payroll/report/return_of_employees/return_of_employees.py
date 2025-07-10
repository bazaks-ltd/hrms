# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _
from frappe.utils import flt

import erpnext
import re

salary_slip = frappe.qb.DocType("Salary Slip")
salary_detail = frappe.qb.DocType("Salary Detail")
salary_component = frappe.qb.DocType("Salary Component")

def clean_name(name):
    # Keep only letters, numbers, and spaces
    return re.sub(r'[^A-Za-z0-9 ]+', ' ', name)

def get_employee_data_map():
    employee = frappe.qb.DocType("Employee")
    result = (
        frappe.qb.from_(employee)
        .select(
            employee.name,
			employee.first_name,
			employee.middle_name,
			employee.last_name,
            employee.nid,
            employee.date_of_joining,
			employee.relieving_date,
			employee.type_of_departure,
            employee.bank_name,
            employee.bank_ac_no,
            employee.edf
        )
        .run(as_dict=True)
    )
    return {row["name"]: row for row in result}

def execute(filters=None):
    if not filters:
        filters = {}

    currency = None
    if filters.get("currency"):
        currency = filters.get("currency")
    company_currency = erpnext.get_company_currency(filters.get("company"))

    salary_slips = get_salary_slips(filters, company_currency)
    if not salary_slips:
        return [], []

    earning_types, ded_types = get_earning_and_deduction_types(salary_slips)
    columns = get_columns(earning_types, ded_types)

    ss_earning_map = get_salary_slip_details(salary_slips, currency, company_currency, "earnings")
    ss_ded_map = get_salary_slip_details(salary_slips, currency, company_currency, "deductions")

    employee_data_map = get_employee_data_map()

    # Group salary slips by employee and sum up totals
    employee_totals = {}

    for ss in salary_slips:
        emp = ss.employee
        emp_data = employee_data_map.get(emp, {})
        if emp not in employee_totals:
            employee_totals[emp] = {
                "employee": emp,
                "employee_surname": f"{emp_data.get('last_name', '')}".strip(),
                "employee_other_names": f"{emp_data.get('first_name') or ''} {emp_data.get('middle_name') or ''}".strip(),
                "nid": emp_data.get("nid"),
                "data_of_joining": emp_data.get("date_of_joining"),
                "date_of_leaving": emp_data.get("relieving_date"),
                "type_of_departure": emp_data.get("type_of_departure"),
                "branch": ss.branch,
                "department": ss.department,
                "designation": ss.designation,
                "rate_code": ss.rate_code,
                "pay_period": ss.pay_period,
                "company": ss.company,
                "no_of_dependents": emp_data.get("edf", 0),
                "bank_name": emp_data.get("bank_name"),
                "bank_account_no": emp_data.get("bank_ac_no"),
                "currency": currency or company_currency,
                "gross_pay": 0,
                "total_deduction": 0,
                "net_pay": 0,
                "total_loan_repayment": 0,
                "leave_without_pay": 0,
                "absent_days": 0,
                "payment_days": 0,
            }
            # Add all earning and deduction types initialized to 0
            for e in earning_types:
                employee_totals[emp][frappe.scrub(e)] = 0
            for d in ded_types:
                employee_totals[emp][frappe.scrub(d)] = 0

        # Sum up values
        if currency == company_currency:
            employee_totals[emp]["gross_pay"] += flt(ss.gross_pay) * flt(ss.exchange_rate)
            employee_totals[emp]["total_deduction"] += flt(ss.total_deduction) * flt(ss.exchange_rate)
            employee_totals[emp]["net_pay"] += flt(ss.net_pay) * flt(ss.exchange_rate)
        else:
            employee_totals[emp]["gross_pay"] += ss.gross_pay
            employee_totals[emp]["total_deduction"] += ss.total_deduction
            employee_totals[emp]["net_pay"] += ss.net_pay

        employee_totals[emp]["total_loan_repayment"] += ss.total_loan_repayment or 0
        employee_totals[emp]["leave_without_pay"] += ss.leave_without_pay or 0
        employee_totals[emp]["absent_days"] += ss.absent_days or 0
        employee_totals[emp]["payment_days"] += ss.payment_days or 0

        # Sum up earnings
        for e in earning_types:
            employee_totals[emp][frappe.scrub(e)] += ss_earning_map.get(ss.name, {}).get(e, 0) or 0
        # Sum up deductions
        for d in ded_types:
            employee_totals[emp][frappe.scrub(d)] += ss_ded_map.get(ss.name, {}).get(d, 0) or 0

    # Prepare data for report
    data = []
    for emp, row in employee_totals.items():
        data.append(row)

    return columns, data


def get_earning_and_deduction_types(salary_slips):
	salary_component_and_type = {_("Earning"): [], _("Deduction"): []}

	for salary_compoent in get_salary_components(salary_slips):
		component_type = get_salary_component_type(salary_compoent)
		salary_component_and_type[_(component_type)].append(salary_compoent)

	return sorted(salary_component_and_type[_("Earning")]), sorted(salary_component_and_type[_("Deduction")])


def update_column_width(ss, columns):
	if ss.branch is not None:
		columns[3].update({"width": 120})
	if ss.department is not None:
		columns[4].update({"width": 120})
	if ss.designation is not None:
		columns[5].update({"width": 120})
	if ss.leave_without_pay is not None:
		columns[9].update({"width": 120})


def get_columns(earning_types, ded_types):
	columns = [
		{
			"label": _("Employee ID"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{
			"label": _("Surname of Employe"),
			"fieldname": "employee_surname",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Other Names of employee"),
			"fieldname": "employee_other_names",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("NID"),
			"fieldname": "nid",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("No. of Dependents"),
			"fieldname": "no_of_dependents",
			"fieldtype": "Int",
			"width": 120,
		},
	]

	for earning in earning_types:
		columns.append(
			{
				"label": earning,
				"fieldname": frappe.scrub(earning),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	columns.append(
		{
			"label": _("Gross Pay"),
			"fieldname": "gross_pay",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		}
	)

	for deduction in ded_types:
		columns.append(
			{
				"label": deduction,
				"fieldname": frappe.scrub(deduction),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	columns.extend(
		[
			{
				"label": _("Loan Repayment"),
				"fieldname": "total_loan_repayment",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
			{
				"label": _("Total Deduction"),
				"fieldname": "total_deduction",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
			{
				"label": _("Net Pay"),
				"fieldname": "net_pay",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
			{
				"label": _("Currency"),
				"fieldtype": "Data",
				"fieldname": "currency",
				"options": "Currency",
				"hidden": 1,
			},
		]
	)
	return columns


def get_salary_components(salary_slips):
	return (
		frappe.qb.from_(salary_detail)
		.where((salary_detail.amount != 0) & (salary_detail.parent.isin([d.name for d in salary_slips])))
		.select(salary_detail.salary_component)
		.distinct()
	).run(pluck=True)


def get_salary_component_type(salary_component):
	return frappe.db.get_value("Salary Component", salary_component, "type", cache=True)


def get_salary_slips(filters, company_currency):
	doc_status = {"Draft": 0, "Submitted": 1, "Cancelled": 2}

	query = frappe.qb.from_(salary_slip).select(salary_slip.star)

	if filters.get("docstatus"):
		query = query.where(salary_slip.docstatus == doc_status[filters.get("docstatus")])

	if filters.get("from_date"):
		query = query.where(salary_slip.start_date >= filters.get("from_date"))

	if filters.get("to_date"):
		query = query.where(salary_slip.end_date <= filters.get("to_date"))

	if filters.get("company"):
		query = query.where(salary_slip.company == filters.get("company"))

	if filters.get("employee"):
		query = query.where(salary_slip.employee == filters.get("employee"))

	if filters.get("currency") and filters.get("currency") != company_currency:
		query = query.where(salary_slip.currency == filters.get("currency"))

	salary_slips = query.run(as_dict=1)

	return salary_slips or []

def get_employee_nid_map():
	employee = frappe.qb.DocType("Employee")

	result = (frappe.qb.from_(employee).select(employee.name, employee.nid)).run()

	return frappe._dict(result)

def get_employee_doj_map():
	employee = frappe.qb.DocType("Employee")

	result = (frappe.qb.from_(employee).select(employee.name, employee.date_of_joining)).run()

	return frappe._dict(result)

def get_employee_bank_name_map():
	employee = frappe.qb.DocType("Employee")

	result = (frappe.qb.from_(employee).select(employee.name, employee.bank_name)).run()

	return frappe._dict(result)


def get_employee_bank_account_map():
	employee = frappe.qb.DocType("Employee")

	result = (frappe.qb.from_(employee).select(employee.name, employee.bank_ac_no)).run()

	return frappe._dict(result)


def get_salary_slip_details(salary_slips, currency, company_currency, component_type):
	salary_slips = [ss.name for ss in salary_slips]

	result = (
		frappe.qb.from_(salary_slip)
		.join(salary_detail)
		.on(salary_slip.name == salary_detail.parent)
		.where((salary_detail.parent.isin(salary_slips)) & (salary_detail.parentfield == component_type))
		.select(
			salary_detail.parent,
			salary_detail.salary_component,
			salary_detail.amount,
			salary_slip.exchange_rate,
		)
	).run(as_dict=1)

	ss_map = {}

	for d in result:
		ss_map.setdefault(d.parent, frappe._dict()).setdefault(d.salary_component, 0.0)
		if currency == company_currency:
			ss_map[d.parent][d.salary_component] += flt(d.amount) * flt(
				d.exchange_rate if d.exchange_rate else 1
			)
		else:
			ss_map[d.parent][d.salary_component] += flt(d.amount)

	return ss_map
