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

def get_custom_field_order():
	return [
		# Taxable Allowances
		"Basic",
		"Unpaid Leave",
		"Coordinator Allowance",
		"Night Shift Allowance", 
		"Overtime 1.5x",
		"Overtime 2.0",
		"Overtime 3x",
		"On Call Allowance",
		"Preavis - 1 month",
		"Bonus pro-rata",
		"Food Allowance",
		"Other Taxable Allowance",
		"Salary Adjustment",
		"Monthly Taxable",
		"Home Allowance",
		"Productivity Bonus",
		"EOY",
		
		# Non-taxable items
		"Busfare",
		"Car Allowance", 
		"Mileage Allowance",
		"Meal Allowance",
		
		# Deductions
		"PAYE",
		"CSG (EE)",
		"NSF (EE)", 
		"Medical Insurance EE",
		"Loan Deduction",
		"Other Deductions",

		# Employer contributions
		"CSG (ER)",
		"NSF (ER)", 
		"Levy",
		"PRGF"
	]

def get_employer_contributions():
	return [
		"CSG (ER)",
		"NSF (ER)", 
		"Levy",
		"PRGF",
		"Medical Insurance ER"
	]

def get_taxable_components():
	"""Define which components are taxable"""
	return [
		"Basic",
		"Coordinator Allowance", 
		"Night Shift Allowance",
		"Overtime 1.5x",
		"Overtime 2.0", 
		"Overtime 3x",
		"On Call Allowance",
		"Preavis - 1 month",
		"Bonus pro-rata",
		"Food Allowance",
		"Home Allowance",
		"Other Taxable Allowance",
		"Productivity Bonus",
		"Unpaid Leave",
		"EOY"
	]

def get_non_taxable_components():
	"""Define which components are non-taxable"""
	return [
		"Busfare",
		"Bus Fare",
		"Car Allowance",
		"Mileage Allowance",
		"Meal Allowance",
		"Other Refund",
		"Other exempt income"
	]

def calculate_taxable_income(row_data, earning_types, ss_earning_map, salary_slip_name):
	"""Calculate taxable income for a salary slip"""
	taxable_components = get_taxable_components()
	taxable_total = 0.0
	
	for component in earning_types:
		if component in taxable_components:
			_component = "Unpaid Leave_E" if component == "Unpaid Leave" else component 
			amount = ss_earning_map.get(salary_slip_name, {}).get(_component, 0)
			if amount:
				if component == "Unpaid Leave":
					taxable_total -= flt(amount)
				else:
					taxable_total += flt(amount)
	
	return taxable_total

def calculate_non_taxable_income(row_data, earning_types, ss_earning_map, salary_slip_name):
	"""Calculate non-taxable income for a salary slip"""
	non_taxable_components = get_non_taxable_components()
	non_taxable_total = 0.0
	
	for component in earning_types:
		if component in non_taxable_components:
			amount = ss_earning_map.get(salary_slip_name, {}).get(component, 0)
			if amount:
					non_taxable_total += flt(amount)
	
	return non_taxable_total

def calculate_total_income(row_data, earning_types, ss_earning_map, salary_slip_name):
	"""Calculate total income (taxable + non-taxable)"""
	total_income = 0.0
	
	for component in earning_types:
		amount = ss_earning_map.get(salary_slip_name, {}).get(component, 0)
		if amount and component not in get_employer_contributions():
			total_income += flt(amount)
	
	return total_income

def calculate_total_csg(row_data, earning_types, ded_types, ss_earning_map, ss_ded_map, salary_slip_name):
	"""Calculate total CSG (Employee + Employer contributions)"""
	total_csg = 0.0
	
	# Get CSG Employee (from deductions)
	csg_employee = ss_ded_map.get(salary_slip_name, {}).get("CSG (EE)", 0)
	if csg_employee:
		total_csg += flt(csg_employee)
	
	# Get CSG Employer (from earnings - since employer contributions are earnings)
	csg_employer = ss_earning_map.get(salary_slip_name, {}).get("CSG (ER)", 0)
	if csg_employer:
		total_csg += flt(csg_employer)
	
	return total_csg

def calculate_total_nsf(row_data, earning_types, ded_types, ss_earning_map, ss_ded_map, salary_slip_name):
	"""Calculate total NSF (Employee + Employer contributions)"""
	total_nsf = 0.0
	
	# Get NSF Employee (from deductions)
	nsf_employee = ss_ded_map.get(salary_slip_name, {}).get("NSF (EE)", 0)
	if nsf_employee:
		total_nsf += flt(nsf_employee)
	
	# Get NSF Employer (from earnings)
	nsf_employer = ss_earning_map.get(salary_slip_name, {}).get("NSF (ER)", 0)
	if nsf_employer:
		total_nsf += flt(nsf_employer)
	
	return total_nsf

def calculate_total_paye(row_data, ded_types, ss_ded_map, salary_slip_name):
	"""Calculate total PAYE (usually just employee PAYE)"""
	paye = ss_ded_map.get(salary_slip_name, {}).get("PAYE", 0)
	return flt(paye) if paye else 0.0

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

	data = []
	for ss in salary_slips:
		emp_data = employee_data_map.get(ss.employee, {})
		row = {
			"salary_slip_id": ss.name,
			"employee": ss.employee,
			"employee_name": clean_name(ss.employee_name),
			"employee_surname": f"{emp_data.get('last_name', '')}".strip(),
			"employee_other_names": f"{emp_data.get('first_name') or ''} {emp_data.get('middle_name') or ''}".strip(),			
			"nid": emp_data.get("nid"),
			"date_of_joining": emp_data.get("date_of_joining"),
			"date_of_leaving": emp_data.get("relieving_date"),
			"type_of_departure": emp_data.get("type_of_departure"),
			"branch": ss.branch,
			"department": ss.department,
			"designation": ss.designation,
			"rate_code": ss.rate_code,
			"pay_period": ss.pay_period,
			"company": ss.company,
			"start_date": ss.start_date,
			"end_date": ss.end_date,
			"leave_without_pay": ss.leave_without_pay,
			"absent_days": ss.absent_days,
			"payment_days": ss.payment_days,
			"no_of_dependents": emp_data.get("edf", 0),
			"bank_name": emp_data.get("bank_name"),
			"bank_account_no": emp_data.get("bank_ac_no"),
			"currency": currency or company_currency,
			"total_loan_repayment": ss.total_loan_repayment,
		}

		update_column_width(ss, columns)

		for e in earning_types:
			if e == "Unpaid Leave":
				deduction_amount = ss_ded_map.get(ss.name, {}).get("Unpaid Leave", 0)
				row.update({frappe.scrub("Unpaid Leave"): deduction_amount})
			else:
				row.update({frappe.scrub(e): ss_earning_map.get(ss.name, {}).get(e)})

		for d in ded_types:
			if d != "Unpaid Leave":
				row.update({frappe.scrub(d): ss_ded_map.get(ss.name, {}).get(d)})

		# Calculate taxable income and total income
		taxable_income = calculate_taxable_income(row, earning_types, ss_earning_map, ss.name)
		non_taxable_income = calculate_non_taxable_income(row, earning_types, ss_earning_map, ss.name)
		total_income = taxable_income + non_taxable_income
		total_csg = calculate_total_csg(row, earning_types, ded_types, ss_earning_map, ss_ded_map, ss.name)
		total_nsf = calculate_total_nsf(row, earning_types, ded_types, ss_earning_map, ss_ded_map, ss.name)
		total_paye = calculate_total_paye(row, ded_types, ss_ded_map, ss.name)
		
		row.update({
			"taxable_income": taxable_income,
			"total_income": total_income,
			"total_csg": total_csg,
			"total_nsf": total_nsf,
			"total_paye": total_paye
		})
		
		if currency == company_currency:
			row.update(
				{
					"gross_pay": flt(ss.gross_pay) * flt(ss.exchange_rate),
					"total_deduction": flt(ss.total_deduction) * flt(ss.exchange_rate),
					"net_pay": flt(ss.net_pay) * flt(ss.exchange_rate),
				}
			)

		else:
			row.update(
				{"gross_pay": ss.gross_pay, "total_deduction": ss.total_deduction, "net_pay": ss.net_pay}
			)

		data.append(row)

	return columns, data


def get_earning_and_deduction_types(salary_slips):
	salary_component_and_type = {_("Earning"): [], _("Deduction"): []}
	all_components = get_salary_components(salary_slips)
	
	# Get the custom field order
	custom_order = get_custom_field_order()
	
	# Separate earnings and deductions based on component type
	for component in all_components:
		component_type = get_salary_component_type(component)
		
		salary_component_and_type[_(component_type)].append(component)
	
	# Sort earnings and deductions according to custom order
	def sort_by_custom_order(components):
		ordered = []
		remaining = components.copy()
		
		# Add components in custom order if they exist
		for field in custom_order:
			# Handle the special case of "Unpaid Leave" display name mapping to "Unpaid Leave_E"
			if field == "Unpaid Leave" and "Unpaid Leave_E" in remaining:
				ordered.append("Unpaid Leave")  # Add the display name
				remaining.remove("Unpaid Leave_E")  # Remove the actual component name
			elif field in remaining:
				ordered.append(field)
				remaining.remove(field)
		
		# Add any remaining components at the end (alphabetically sorted)
		ordered.extend(sorted(remaining))
		return ordered
    
	earnings_ordered = sort_by_custom_order(salary_component_and_type[_("Earning")])
	deductions_ordered = sort_by_custom_order(salary_component_and_type[_("Deduction")])

	return earnings_ordered, deductions_ordered

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
	employer_contributions = get_employer_contributions()
	taxable_components = get_taxable_components()
	non_taxable_components = get_non_taxable_components()
	taxable_earnings = [e for e in earning_types if e in taxable_components]
	non_taxable_earnings = [e for e in earning_types if e in non_taxable_components]
	employer_contrib_types = [e for e in earning_types if e in employer_contributions]

	columns = [
		{
			"label": _("Salary Slip ID"),
			"fieldname": "salary_slip_id",
			"fieldtype": "Link",
			"options": "Salary Slip",
			"width": 150,
		},
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{
			"label": _("NID"),
			"fieldname": "nid",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Surname"),
			"fieldname": "employee_surname",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Other Names"),
			"fieldname": "employee_other_names",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Full Name"),
			"fieldname": "employee_name",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Designation"),
			"fieldname": "designation",
			"fieldtype": "Link",
			"options": "Designation",
			"width": 120,
		},
		{
			"label": _("Date of Joining"),
			"fieldname": "date_of_joining",
			"fieldtype": "Date",
			"width": 80,
		},
		{
			"label": _("Date of Leaving"),
			"fieldname": "date_of_leaving",
			"fieldtype": "Date",
			"width": 80,
		},
		{
			"label": _("Leavers Type"),
			"fieldname": "type_of_departure",
			"fieldtype": "Data",
			"width": 80,
		},
		{
			"label": _("Bank Name"),
			"fieldname": "bank_name",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Bank Ac. No."),
			"fieldname": "bank_account_no",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("No. of Dependents"),
			"fieldname": "no_of_dependents",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"label": _("Rate Code"),
			"fieldname": "rate_code",
			"fieldtype": "Data",
			"width": 60,
		},
		{
			"label": _("Pay Period"),
			"fieldname": "pay_period",
			"fieldtype": "Data",
			"width": 60,
		},
		{
			"label": _("Leave Without Pay"),
			"fieldname": "leave_without_pay",
			"fieldtype": "Float",
			"width": 50,
		},
		{
			"label": _("Absent Days"),
			"fieldname": "absent_days",
			"fieldtype": "Float",
			"width": 50,
		},
		{
			"label": _("Payment Days"),
			"fieldname": "payment_days",
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 120,
		},
		{
			"label": _("Branch"),
			"fieldname": "branch",
			"fieldtype": "Link",
			"options": "Branch",
			"width": -1,
		},
		{
			"label": _("Department"),
			"fieldname": "department",
			"fieldtype": "Link",
			"options": "Department",
			"width": -1,
		},
		{
			"label": _("Start Date"),
			"fieldname": "start_date",
			"fieldtype": "Data",
			"width": 80,
		},
		{
			"label": _("End Date"),
			"fieldname": "end_date",
			"fieldtype": "Data",
			"width": 80,
		},
	]

	for earning in taxable_earnings:
		columns.append(
			{
				"label": earning,
				"fieldname": frappe.scrub(earning),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	columns.extend([
			{
				"label": _("Taxable Income"),
				"fieldname": "taxable_income",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
			{
				"label": _("Total Income"),
				"fieldname": "total_income",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		])

	columns.append(
		{
			"label": _("Gross Pay"),
			"fieldname": "gross_pay",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		}
	)

	for earning in non_taxable_earnings:
		columns.append(
			{
				"label": earning,
				"fieldname": frappe.scrub(earning),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	for deduction in ded_types:
		if deduction != "Unpaid Leave":
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
			# {
			# 	"label": _("Loan Repayment"),
			# 	"fieldname": "total_loan_repayment",
			# 	"fieldtype": "Currency",
			# 	"options": "currency",
			# 	"width": 120,
			# },
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

	for contrib in employer_contrib_types:
		columns.append(
			{
				"label": contrib,
				"fieldname": frappe.scrub(contrib),
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			}
		)

	columns.extend([
		{
			"label": _("Total CSG"),
			"fieldname": "total_csg",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Total NSF"),
			"fieldname": "total_nsf", 
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"label": _("Total PAYE"),
			"fieldname": "total_paye",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		}
	])

	return columns


def get_salary_components(salary_slips):
	statistical_components = ["mtax", "Monthly Taxable"]  # Add others as needed
	
	# Get regular components (amount != 0)
	regular_components = (
		frappe.qb.from_(salary_detail)
		.where((salary_detail.amount != 0) & (salary_detail.parent.isin([d.name for d in salary_slips])))
		.select(salary_detail.salary_component)
		.distinct()
	).run(pluck=True)
	
	# Get statistical components from salary slips
	statistical_in_slips = (
		frappe.qb.from_(salary_detail)
		.where(
			(salary_detail.parent.isin([d.name for d in salary_slips])) &
			(salary_detail.salary_component.isin(statistical_components))
		)
		.select(salary_detail.salary_component)
		.distinct()
	).run(pluck=True)
	
	return list(set(regular_components + statistical_in_slips))


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
