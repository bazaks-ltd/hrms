# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from erpnext.setup.doctype import employee
import frappe
from frappe import _
from frappe.utils import flt
from datetime import date
from frappe.utils.data import getdate
from hrms.payroll.doctype.salary_slip.salary_slip import calculate_exempt_transport_allowance
import erpnext
import re

salary_slip = frappe.qb.DocType("Salary Slip")
salary_detail = frappe.qb.DocType("Salary Detail")
salary_component = frappe.qb.DocType("Salary Component")

deduction_map = {
    2025: {1: 110000, 2: 190000, 3: 275000, 4: 355000},
}

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
				"busfare": 0,
				"salary_wages_allowances_bonus_special_allowance_2024": 0,
				"transport_travelling_allowance": 0,
				"total_deductions_edf": 0,
				"exempt_emoluments": 0,
				"paye": 0,
            	"entertainment_allowance": 0
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

		# Calculate basic salary + overtime
        basic_salary = ss_earning_map.get(ss.name, {}).get("Basic", 0) or 0
        car_allowance = ss_earning_map.get(ss.name, {}).get("Car Allowance", 0) or 0
        busfare = ss_earning_map.get(ss.name, {}).get("Busfare", 0) or 0
        overtime_15x = ss_earning_map.get(ss.name, {}).get("Overtime 1.5x", 0) or 0
        overtime_2x = ss_earning_map.get(ss.name, {}).get("Overtime 2.0", 0) or 0
        overtime_3x = ss_earning_map.get(ss.name, {}).get("Overtime 3x", 0) or 0
        mileage = ss_earning_map.get(ss.name, {}).get("Mileage Allowance", 0) or 0
        coordinator_allowance = ss_earning_map.get(ss.name, {}).get("Coordinator Allowance", 0) or 0
        night_shift_allowance = ss_earning_map.get(ss.name, {}).get("Night Shift Allowance", 0) or 0
        on_call_allowance = ss_earning_map.get(ss.name, {}).get("On Call Allowance", 0) or 0
        other_taxable_allowance = ss_earning_map.get(ss.name, {}).get("Other Taxable Allowance", 0) or 0
        salary_adjustment = ss_earning_map.get(ss.name, {}).get("Salary Adjustment", 0) or 0	
        unpaid_leaves = ss_ded_map.get(ss.name, {}).get("Unpaid Leave", 0) or 0
        other_deductions = ss_ded_map.get(ss.name, {}).get("Other Taxable Deductions", 0) or 0
        employee_totals[emp]["salary_wages_allowances_bonus_special_allowance_2024"] += basic_salary + overtime_15x + overtime_2x + overtime_3x + coordinator_allowance	+ night_shift_allowance + other_taxable_allowance + salary_adjustment + on_call_allowance - unpaid_leaves - other_deductions
        employee_totals[emp]["exempt_emoluments"] += mileage + busfare + (calculate_exempt_transport_allowance(basic_salary, car_allowance) if basic_salary and car_allowance else 0)

    bonus_year_date = date(getdate(filters.get("to_date")).year - 1, 12, 31)
			
    # Prepare data for report
    data = []
    for emp, row in employee_totals.items():
        emp_data = employee_data_map.get(emp, {})
        bonus_including_end_of_year = frappe.db.get_value(
            "EOY Bonus",
            {"nid": emp_data.get("nid"), "bonus_year": bonus_year_date},
            "eoy_bonus"
        )
        
        # Add bonus only once per employee
        if bonus_including_end_of_year:
            row["salary_wages_allowances_bonus_special_allowance_2024"] += flt(bonus_including_end_of_year)
            print(f"Added bonus {bonus_including_end_of_year} for employee {emp}")

        edf = int(emp_data.get("edf"))
        year_map = deduction_map.get(2025, {})
        row['total_deductions_edf'] = year_map.get(int(edf), 0)
        row['paye_withheld'] = row['paye']
        print("Row: ", row)
        row['transport_travelling_allowance'] = row['car_allowance'] + row['mileage_allowance'] + row['busfare']

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
			"label": _("ID"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 120,
		},
		{
			"label": _("Surname of Employee"),
			"fieldname": "employee_surname",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Other Names of Employee"),
			"fieldname": "employee_other_names",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Employee ID"),
			"fieldname": "nid",
			"fieldtype": "Data",
			"width": 120,
		},	
		{
				"label": _("Salary/Wages/Allowances/Bonus/Special Allowance 2024 (MUR)"),
				"fieldname": "salary_wages_allowances_bonus_special_allowance_2024",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},	
		{
				"label": _("Entertainment Allowance (MUR)"),
				"fieldname": "entertainment_allowance",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Transport/Travelling Allowance/ Reimbursement or Travelling Expenses (MUR)"),
				"fieldname": "transport_travelling_allowance",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Reimbursement of Other Expenses (MUR)"),
				"fieldname": "reimbursement_of_other_expenses",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Car Benefit (MUR)"),
				"fieldname": "car_benefit",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("House Benefit (MUR)"),
				"fieldname": "house_benefit",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Tax Benefit (MUR)"),
				"fieldname": "tax_benefit",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Other Benefit (MUR)"),
				"fieldname": "other_benefit",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Lump Sum (MUR)"),
				"fieldname": "lump_sum",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Retirement Pension/ Annuity (MUR)"),
				"fieldname": "retirement_pension_annuity_rs",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Exempt Emoluments (MUR)	"),
				"fieldname": "exempt_emoluments",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("Total deductions claimed in EDF (MUR)"),
				"fieldname": "total_deductions_edf",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		},
		{
				"label": _("PAYE for Income Tax (MUR)"),
				"fieldname": "paye_withheld",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
		}
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

@frappe.whitelist()
def export_roe(filters):
    """
    Export specific rows from the Return of Employees report
    """
    try:
        # Convert string filters back to dict if needed
        if isinstance(filters, str):
            import json
            filters = json.loads(filters)
        
        # Get the report data using the existing execute function
        columns, data = execute(filters)
        
        # Define specific columns to export for ROE
        export_columns = [
            "nid",  # Employee ID
            "employee_surname",  # Surname of employee
            "employee_other_names",  # Other Names of employee
            "salary_wages_allowances_bonus_special_allowance_2024",  # Salary/Wages/Allowances/Bonus/Special Allowance 2024 (MUR)
            "entertainment_allowance",  # Entertainment Allowance (MUR)
            "transport_travelling_allowance",  # Transport/Travelling Allowance/ Reimbursement or Travelling Expenses (MUR)
            "reimbursement_of_other_expenses",  # Reimbursement of Other Expenses (MUR)
            "car_benefit",  # Car Benefit (MUR)
            "house_benefit",  # House Benefit (MUR)
            "tax_benefit",  # Tax Benefit (MUR)
            "other_benefit",  # Other Benefit (MUR)
            "lump_sum",  # Lump sum (MUR)
            "retirement_pension_annuity_rs",  # Retirement Pension/ Annuity (MUR)
            "exempt_emoluments",  # Exempt Emoluments (MUR)
            "total_deductions_edf",  # Total deductions claimed in EDF (MUR)
            "paye_withheld"  # PAYE for Income Tax (MUR)
        ]
        
        # Filter columns to only include the ones we want to export
        filtered_columns = []
        for col in columns:
            if col.get("fieldname") in export_columns:
                filtered_columns.append(col)
        
        # Create Excel file or CSV
        from frappe.utils.xlsxutils import make_xlsx
        from frappe.utils.file_manager import save_file
        import io
        
        # Prepare data for Excel export
        xlsx_data = []
        
        # Add headers (only for selected columns)
        headers = [col.get("label") or col.get("fieldname") for col in filtered_columns]
        xlsx_data.append(headers)
        
        # Add data rows (only selected columns)
        for row in data:
            row_data = []
            for col in filtered_columns:
                fieldname = col.get("fieldname")
                value = row.get(fieldname, "")
                row_data.append(value)
            xlsx_data.append(row_data)
        
        # Generate Excel file
        xlsx_file = make_xlsx(xlsx_data, "Return of Employees Export")
        
        # Save the file using frappe.get_doc method (more reliable)
        file_name = f"ROE_Export_{frappe.utils.now().replace(' ', '_').replace(':', '-')}.xlsx"
        
        # Create file document
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name,
            "content": xlsx_file.getvalue(),
            "is_private": 1,
            "folder": "Home/Attachments"
        })
        file_doc.save()
        
        # Return success response with file URL
        return {
            "success": True,
            "message": f"Exported {len(data)} records with {len(filtered_columns)} columns successfully",
            "file_url": file_doc.file_url,
            "file_name": file_name
        }
        
    except Exception as e:
        frappe.log_error(f"Export ROE Error: {str(e)}")
        return {
            "success": False,
            "error": f"Export failed: {str(e)}"
        }