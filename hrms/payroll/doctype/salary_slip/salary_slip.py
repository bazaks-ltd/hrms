# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import unicodedata
from datetime import date, datetime, timedelta
import math
import frappe
from frappe import _, msgprint
from frappe.model.naming import make_autoname
from frappe.query_builder import Order
from frappe.query_builder.functions import Count, Sum
from frappe.model.docstatus import DocStatus
from frappe.utils import (
	add_days,
	ceil,
	cint,
	cstr,
	date_diff,
	floor,
	flt,
	formatdate,
	get_first_day,
	get_link_to_form,
	getdate,
	money_in_words,
	rounded,
)
from frappe.utils.background_jobs import enqueue

import erpnext
from erpnext.accounts.utils import get_fiscal_year
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
from erpnext.utilities.transaction_base import TransactionBase

from hrms.hr.utils import validate_active_employee
from hrms.payroll.doctype.additional_salary.additional_salary import get_additional_salaries
from hrms.payroll.doctype.employee_benefit_application.employee_benefit_application import (
	get_benefit_component_amount,
)
from hrms.payroll.doctype.employee_benefit_claim.employee_benefit_claim import (
	get_benefit_claim_amount,
	get_last_payroll_period_benefits,
)
from hrms.payroll.doctype.payroll_entry.payroll_entry import get_start_end_dates
from hrms.payroll.doctype.payroll_period.payroll_period import (
	get_payroll_period,
	get_period_factor,
)
from hrms.payroll.doctype.salary_slip.salary_slip_loan_utils import (
	cancel_loan_repayment_entry,
	make_loan_repayment_entry,
	set_loan_repayment,
)
from hrms.payroll.utils import sanitize_expression
from hrms.utils.holiday_list import get_holiday_dates_between

# cache keys
HOLIDAYS_BETWEEN_DATES = "holidays_between_dates"
LEAVE_TYPE_MAP = "leave_type_map"
SALARY_COMPONENT_VALUES = "salary_component_values"
TAX_COMPONENTS_BY_COMPANY = "tax_components_by_company"

NIGHT_SHIFT_CODES = ["NSG 2", "NSG 1", "NSG N", "SEC N", "DRIVER N", "N"]
ON_CALL_CODE = 'CALL C'


SALARY_COMPONENT_TO_EMOLUMENT_TYPE = {
    "Basic": "salary_wages_basic",
	"Overtime 1.5x": "salary_wages_basic",
	"Overtime 2.0": "salary_wages_basic",
	"Overtime 3x": "salary_wages_basic",
	"Night Shift Allowance": "salary_wages_basic",
	"On Call Allowance": "salary_wages_basic",
	"Salary Adjustment": "salary_wages_basic",
	"Other Taxable Allowance": "salary_wages_basic",
	"Coordinator Allowance": "salary_wages_basic",
	"Other Taxable Deductions": "salary_wages_basic",
	"Bonus pro-rata": "salary_wages_basic",
	"Productivity Bonus": "salary_wages_basic",
	"Preavis - 1 month": "salary_wages_basic",
	"Busfare": "transport_allowance",
	"Unpaid Leave": "unpaid_leave",
	"Mileage Allowance": "reimbursement_travelling_expenses",
	"EOY": "salary_wages_basic",
    "House Rent Allowance": "allowances_hra",
    "Car Allowance": "transport_allowance",
    "Medical Allowance": "allowances_medical",
	"PAYE": "tax_withheld_and_remitted",
	"PRGF": "contributions_to_prgf"
}

deduction_map = {
    2025: {1: 110000, 2: 190000, 3: 275000, 4: 355000},
}

def calculate_exempt_transport_allowance(basic_salary, car_allowance):
		MAX_EXEMPT = 20000
		twenty_five_percent_basic = basic_salary * 0.25
		exempt_amount = min(car_allowance, twenty_five_percent_basic, MAX_EXEMPT)
		
		return exempt_amount

def get_salary_components_via_db(salary_slip_name):		
		# Get earnings
		earnings = frappe.db.get_all(
			"Salary Detail",
			filters={
				"parent": salary_slip_name,
				"parenttype": "Salary Slip",
				"parentfield": "earnings"
			},
			fields=["salary_component", "amount"]
		)
		
		# Get deductions
		deductions = frappe.db.get_all(
			"Salary Detail", 
			filters={
				"parent": salary_slip_name,
				"parenttype": "Salary Slip", 
				"parentfield": "deductions"
			},
			fields=["salary_component", "amount"]
		)
		
		# Convert to dictionaries for easy lookup
		earnings_dict = {item['salary_component']: item['amount'] for item in earnings}
		deductions_dict = {item['salary_component']: item['amount'] for item in deductions}
		
		return earnings_dict, deductions_dict

class SalarySlip(TransactionBase):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.series = f"Sal Slip/{self.employee}/.#####"
		self.whitelisted_globals = {
			"int": int,
			"float": float,
			"long": int,
			"round": round,
			"date": date,
			"getdate": getdate,
			"ceil": ceil,
			"floor": floor,
			"eround": self.eround,
			"calc_working_days": self.calc_working_days,
			"calc_last_working_days": self.calc_last_working_days,
			"get_salary_increase_for_period": self.get_salary_increase_for_period,
			"night_shift_count": self.night_shift_count,
			"strict_night_shift_count": self.strict_night_shift_count,
			"night_shifts_assigned": self.night_shifts_assigned,
			"get_approved_overtime_count": self.get_approved_overtime_count,
			"get_attendance_count": self.get_attendance_count,
			"on_call_count": self.on_call_count,
			"get_unpaid_leaves": self.get_unpaid_leaves,
			"calc_miles_travelled": self.calc_miles_travelled,
			"get_days_attended": self.get_days_attended,
			"get_employee_dept": self.get_employee_dept,
			"bus_fare_deductions": self.bus_fare_deductions,
			"calc_total_remuneration": self.calc_total_remuneration,
			"get_employee_insurance_deduction": self.get_employee_insurance_deduction,
			"get_employer_insurance_contribution": self.get_employer_insurance_contribution,
		}		

	def eround(self, value, decimals=0):
		"""
		value = flt(value)
		
		if value % 1 >= 0.5:
			return math.ceil(value)
		else :
			return math.floor(value)
		"""
		return round(flt(value), decimals)
	
	@frappe.whitelist()
	def calc_working_days(self, join_date, scheme):
		scheme = int(scheme)
		# Get the last day of the month
		next_month = join_date.replace(day=28) + timedelta(days=4)  # Ensures moving into the next month
		last_day_of_month = next_month - timedelta(days=next_month.day)		
		# Initialize variables
		working_days = 0
		current_date = join_date		
		# Loop through days from join_date to last day of the month
		while current_date <= last_day_of_month:
    		# Exclude weekends (Saturday=5, Sunday=6)
			if scheme == 22:
				if current_date.weekday() < 5:
					working_days += 1
			else:
				if current_date.weekday() < 6:
					working_days += 1
			current_date += timedelta(days=1)		    
		return working_days

	@frappe.whitelist()
	def calc_total_remuneration(self):
		"""
		Calculate total (taxable) remuneration from December of the previous year to current period
		for calculation of bonus pro-rata.
		"""
		if not self.employee or not self.end_date:
			return 0

		# Get date range: Dec 1 of previous year to self.end_date
		end_date = getdate(self.end_date)
		start_date = f"{end_date.year - 1}-12-01"
		end_date_str = end_date.strftime("%Y-%m-%d")

		result = frappe.db.sql("""
			SELECT SUM(sd.amount) as total_taxable_pcc_amount
			FROM `tabSalary Detail` sd
			JOIN `tabSalary Component` sc ON sd.abbr = sc.salary_component_abbr
			WHERE sd.parent IN (
				SELECT name 
				FROM `tabSalary Slip` 
				WHERE employee = %s
				AND end_date >= %s
				AND end_date <= %s
			)
			AND sc.is_taxable_pcc = 1
		""", (self.employee, start_date, end_date_str), as_dict=True)

		total_remuneration = result[0]["total_taxable_pcc_amount"] if result and result[0]["total_taxable_pcc_amount"] else 0
		return total_remuneration
		
	@frappe.whitelist()
	def calc_last_working_days(self, scheme):
		"""
		Calculate working days from the later of the first day of the month of end_date or the employee's joining_date,
		up to the employee's leaving_date (or end_date), using the given scheme (22/26).
		"""

		scheme = int(scheme)
		# Get the first day of the month for end_date
		month_start = get_first_day(self.end_date)
		# Use employee's joining date if after month start
		start_date = max(getdate(month_start), getdate(self.joining_date))
		# Use employee's relieving date, or end_date if not set
		last_day = self.leaving_date or self.end_date
		if not last_day or getdate(last_day) < start_date:
			return 0

		working_days = 0
		current_date = start_date
		last_day = getdate(last_day)

		while current_date <= last_day:
			# Exclude weekends (Saturday=5, Sunday=6) for scheme 22, include Saturday for 26
			if scheme == 22:
				if current_date.weekday() < 5:
					working_days += 1
			else:
				if current_date.weekday() < 6:
					working_days += 1
			current_date += timedelta(days=1)
		return working_days
	
	# Calculate number of days on night shifts during payroll period
	@frappe.whitelist()
	def strict_night_shift_count(self):
		filters = {
			'employee': self.employee,
			'status': "Present",
			'docstatus': 1,
			'attendance_date': ['between', [self.start_date, self.end_date]],
			'shift': ['in', NIGHT_SHIFT_CODES]
		}

		night_shifts = frappe.db.count('Attendance', filters)

		return night_shifts

	# Calculate number of days on night shifts during payroll period
	@frappe.whitelist()
	def night_shift_count(self):
		filters = {
			'employee': self.employee,
			'status': "Present",
			'docstatus': 1,
			'attendance_date': ['between', [self.start_date, self.end_date]],
			'shift': ['in', NIGHT_SHIFT_CODES]
		}

		night_shifts = frappe.db.count('Attendance', filters)
	
		additional_night_shifts = frappe.db.count(
			"Employee Overtime",
			filters={
				"employee": self.employee,
				"date": ["between", [self.start_date, self.end_date]],
				"eligible_for_night_shift": 1,
				"workflow_state": "Approved",
				"docstatus": 1
			}
		)
			
		return night_shifts + additional_night_shifts
	
	@frappe.whitelist()
	def night_shifts_assigned(self):
		filters = {
			'employee': self.employee,
			'start_date': ['>=', self.start_date],
			'end_date': ['<=', self.end_date],
			'shift_type': ['in', NIGHT_SHIFT_CODES],
			'docstatus': 1
		}
		count = frappe.db.count('Shift Assignment', filters)
		return count

	@frappe.whitelist()
	def get_unpaid_leaves(self):
		"""
		Get the total count of approved unpaid leave days for the employee
		during the payroll period, where the leave type has is_lwp set to True.
		"""
		LeaveApplication = frappe.qb.DocType("Leave Application")
		LeaveType = frappe.qb.DocType("Leave Type")

		# Build the query
		query = (
			frappe.qb.from_(LeaveApplication)
			.inner_join(LeaveType)
			.on(LeaveApplication.leave_type == LeaveType.name)
			.select(
				LeaveApplication.from_date,
				LeaveApplication.to_date, 
				LeaveApplication.total_leave_days,
				LeaveApplication.half_day,
				LeaveApplication.half_day_date
			)
			.where(
				(LeaveApplication.employee == self.employee)
				& (LeaveApplication.from_date <= self.end_date)
				& (LeaveApplication.to_date >= self.start_date)
				& (LeaveApplication.status == "Approved")  # Only approved leaves
				& (LeaveType.is_lwp == 1)  # Filter for leave types where is_lwp is True
			)
		)

		# Execute the query and calculate the total unpaid leave days
		unpaid_leaves = 0
		leave_applications = query.run(as_dict=True)

		for leave in leave_applications:
			# Calculate the overlap between the leave period and the payroll period
			leave_start = max(getdate(leave["from_date"]), getdate(self.start_date))
			leave_end = min(getdate(leave["to_date"]), getdate(self.end_date))
			
			# Calculate overlapping days
			overlapping_days = (leave_end - leave_start).days + 1
			# Adjust for half-day leave
			if leave.get("half_day") and leave.get("half_day_date"):
				half_day_date = getdate(leave["half_day_date"])
				if leave_start <= half_day_date <= leave_end:
					overlapping_days -= 0.5  # Subtract 0.5 for the half-day

			unpaid_leaves += overlapping_days
		
		return unpaid_leaves

	def get_days_attended(self):
		# Count attendance records marked as "Present"
		attended = frappe.db.count("Attendance", {
			"employee": self.employee,
			"attendance_date": ["between", [self.start_date, self.end_date]],
			"status": "Present",
			"docstatus": 1
		})
		
		half_days = frappe.db.count("Attendance", {
			"employee": self.employee,
			"attendance_date": ["between", [self.start_date, self.end_date]],
			"status": "Half Day",
			"docstatus": 1
		})
		
		# Calculate total (counting half days as full for bus fare purposes)
		total_attended = attended + half_days
		
		return total_attended
	
	@frappe.whitelist()
	def calc_miles_travelled(self):
		filters = {
			'employee': self.employee,
			'date': ['between', [self.start_date, self.end_date]],
			'docstatus': 1 # only submitted records
		}

		records = frappe.db.get_all(
			'Mileage Reimbursement',
			filters=filters,
			fields=['no_of_miles']
		)

		total_miles = sum(r['no_of_miles'] for r in records if r['no_of_miles'])
		return total_miles
	
	@frappe.whitelist()
	def bus_fare_deductions(self):
		filters = {
			'employee': self.employee,
			'date': ['between', [self.start_date, self.end_date]],
			'docstatus': 1 # only submitted records
		}

		records = frappe.db.get_all(
			'Mileage Reimbursement',
			filters=filters,
			fields=['no_of_miles', 'deduct_from_bf', 'travel_days']
		)

		deductions = sum(float(r['travel_days']) for r in records if r['deduct_from_bf'])
		return deductions

	# Calculate number of days on call during payroll period
	@frappe.whitelist()
	def on_call_count(self):
		filters = {
			'employee': self.employee,
			'shift_type': ON_CALL_CODE,
			'docstatus': 1 
		}
		shift_assignments = frappe.get_all(
			'Shift Assignment',
			filters=filters,
			fields=['start_date', 'end_date']
		)
		
		total_days = 0
		for shift in shift_assignments:
			# Get the start and end dates of the shift assignment
			shift_start = frappe.utils.getdate(shift['start_date'])
			shift_end = frappe.utils.getdate(shift['end_date'])

			# Calculate the overlap with the salary slip period
			overlap_start = max(shift_start, frappe.utils.getdate(self.start_date))
			overlap_end = min(shift_end, frappe.utils.getdate(self.end_date))

			# Only include the overlapping days
			if overlap_start <= overlap_end:
				overlapping_days = (overlap_end - overlap_start).days + 1
				total_days += overlapping_days
		
		return total_days
	
	@frappe.whitelist()
	def get_salary_increase_for_period(self, employee=None, start_date=None, end_date=None):
		"""
		Get salary increase details if there's a Salary History record
		effective within the given payslip period.
		
		Returns dict with:
		- has_increase: bool
		- change_amount: float
		- effective_date: date
		- change_type: str
		- days_before: int (days at old salary)
		- days_after: int (days at new salary)
		"""
		# Use self values if parameters not provided
		employee = employee or self.employee
		start_date = getdate(start_date) if start_date else getdate(self.start_date)
		end_date = getdate(end_date) if end_date else getdate(self.end_date)
		
		# Get salary history records effective within this period
		salary_history = frappe.db.sql("""
			SELECT 
				name,
				effective_from_date,
				change_amount,
				change_type,
				previous_basic_salary,
				new_basic_salary
			FROM `tabSalary History`
			WHERE employee = %(employee)s
				AND docstatus = 1
				AND effective_from_date >= %(start_date)s
				AND effective_from_date <= %(end_date)s
			ORDER BY effective_from_date DESC
			LIMIT 1
		""", {
			"employee": employee,
			"start_date": start_date,
			"end_date": end_date
		}, as_dict=True)
		
		if not salary_history:
			return {
				"has_increase": False,
				"change_amount": 0,
				"effective_date": None,
				"change_type": None,
				"days_before": 0,
				"days_after": 0
			}
		
		history = salary_history[0]
		effective_date = getdate(history.effective_from_date)
		
		# Calculate days before and after the increase
		# Days before = from start_date to day before effective_date
		from frappe.utils import date_diff, add_days
		
		days_before = date_diff(effective_date, start_date)
		days_after = date_diff(end_date, effective_date) + 1  # Include the effective date
		
		# Ensure days are not negative
		days_before = max(0, days_before)
		days_after = max(0, days_after)
		
		return {
			"has_increase": True,
			"change_amount": history.change_amount,
			"effective_date": history.effective_from_date,
			"change_type": history.change_type,
			"days_before": days_before,
			"days_after": days_after,
			"previous_basic_salary": history.previous_basic_salary,
			"new_basic_salary": history.new_basic_salary
		}
	
	@frappe.whitelist()
	def get_attendance_count(self):
		filters = {
			'employee': self.employee,
			'status': "Present",
			'docstatus': 1,
			'attendance_date': ['between', [self.start_date, self.end_date]],
		}
		return frappe.db.count('Attendance', filters)

	@frappe.whitelist()
	def get_holiday_hours(self):
		"""
		Calculate total hours worked on holidays during the payroll period.
		Uses the get_shift_datetimes function to determine shift start and end times.
		Loads Holiday List {year} for each year covered by the period; falls back to
		the company default_holiday_list when a year-named list does not exist.
		"""
		company = frappe.db.get_value("Employee", self.employee, "company")
		default_holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")

		start_date = getdate(self.start_date)
		end_date = getdate(self.end_date)
		period_years = {start_date.year, end_date.year}

		days_worked_holidays = []
		holiday_lists_used = []

		for year in sorted(period_years):
			year_list = f"Holiday List {year}"
			if frappe.db.exists("Holiday List", year_list):
				list_name = year_list
			elif default_holiday_list and frappe.db.exists("Holiday List", default_holiday_list):
				list_name = default_holiday_list
			else:
				continue

			if list_name in holiday_lists_used:
				continue
			holiday_lists_used.append(list_name)

			holidays_doc = frappe.get_doc("Holiday List", list_name)
			days_worked_holidays.extend(
				h.holiday_date
				for h in holidays_doc.holidays
				if h.holiday_date >= start_date and h.holiday_date <= end_date
			)

		total_holiday_hours = 0
		debug_log = []
		debug_log.append(f"Employee: {self.employee}")
		debug_log.append(f"Period: {self.start_date} to {self.end_date}")
		debug_log.append(f"Holiday lists used: {holiday_lists_used}")
		debug_log.append(f"Holidays in period: {sorted(set(days_worked_holidays))}")
		debug_log.append("=" * 60)
		
		for day in sorted(set(days_worked_holidays)):
			day_before = day - timedelta(days=1)
			
			leave_attendance_holiday = frappe.db.get_value(
				"Attendance",
				{
					"employee": self.employee,
					"attendance_date": day,
					"status": ["in", ["Absent", "On Leave"]],
					"docstatus": 1
				},
				"status"
			)
			
			if leave_attendance_holiday:
				debug_log.append(f"SKIPPED: {day} - on leave/absent ({leave_attendance_holiday})")
				continue
			
			holiday_start = datetime.combine(day, datetime.min.time())
			holiday_end = datetime.combine(day, datetime.max.time())

			shift_assignments = frappe.get_all(
				'Shift Assignment',
				filters={
					'employee': self.employee,
					'start_date': ['<=', day],
					'end_date': ['>=', day_before],
					'shift_type': ['!=', ON_CALL_CODE],
					'docstatus': 1
				},
				fields=['name', 'shift_type', 'start_date', 'end_date']
			)

			debug_log.append(f"\n=== Holiday: {day} ===")
			debug_log.append(f"holiday_start: {holiday_start} | holiday_end: {holiday_end}")
			debug_log.append(f"Shift assignments found: {len(shift_assignments)}")
			for sa in shift_assignments:
				debug_log.append(f"  -> {sa['name']} | {sa['shift_type']} | {sa['start_date']} to {sa['end_date']}")

			day_total_hours = 0
			for assignment in shift_assignments:
				assignment_hours = 0
				attendance = frappe.db.get_value(
					"Attendance",
					{
						"employee": self.employee,
						"attendance_date": day,
						"status": ["in", ["Present", "Half Day"]],
						"docstatus": 1
					},
					["name"]
				)

				attendance_day_before = frappe.db.get_value(
					"Attendance",
					{
						"employee": self.employee,
						"attendance_date": day_before,
						"status": ["in", ["Present", "Half Day"]],
						"docstatus": 1
					},
					["name"]
				)

				debug_log.append(f"\n  Assignment: {assignment['name']} ({assignment['shift_type']})")
				debug_log.append(f"  Attendance on holiday ({day}): {attendance}")
				debug_log.append(f"  Attendance day before ({day_before}): {attendance_day_before}")

				if not attendance and not attendance_day_before:
					debug_log.append(f"  SKIPPED: No attendance on {day} or {day_before}")
					continue
				
				shift_datetimes = self.get_shift_datetimes(assignment)

				debug_log.append(f"  Shift datetimes for {assignment['shift_type']}:")
				for i, s in enumerate(shift_datetimes):
					debug_log.append(f"    [{i}] start={s['shift_start']}, end={s['shift_end']}")

				for shift_idx, shift in enumerate(shift_datetimes):
					shift_start = shift["shift_start"]
					shift_end = shift["shift_end"]

					overlap_start = max(shift_start, holiday_start)
					overlap_end = min(shift_end, holiday_end)

					if overlap_end > overlap_start:
						shift_start_date = shift_start.date()
						has_valid_attendance = (
							(shift_start_date == day and attendance) or
							(shift_start_date == day_before and attendance_day_before)
						)

						hours_worked = (overlap_end - overlap_start).total_seconds() / 3600

						debug_log.append(f"\n    Shift [{shift_idx}]: {shift_start} -> {shift_end}")
						debug_log.append(f"    Overlap: {overlap_start} -> {overlap_end}")
						debug_log.append(f"    Raw overlap hours: {hours_worked:.2f}")
						debug_log.append(f"    shift_start_date: {shift_start_date} | == day: {shift_start_date == day} | == day_before: {shift_start_date == day_before}")
						debug_log.append(f"    has_valid_attendance: {has_valid_attendance}")
						debug_log.append(f"    Will deduct lunch: {shift_start_date == day}")

						if has_valid_attendance:
							assignment_hours += hours_worked
							if shift_start_date == day:
								assignment_hours = assignment_hours - 1

				debug_log.append(f"  >> Assignment total: {assignment_hours:.2f} hours")
				day_total_hours += assignment_hours
			
			debug_log.append(f">> Day total for {day}: {day_total_hours:.2f} hours")
			total_holiday_hours += day_total_hours
		
		debug_log.append("=" * 60)
		debug_log.append(f"FINAL TOTAL holiday hours: {total_holiday_hours:.2f}")

		frappe.log_error(
			title=f"Holiday Hours Debug - {self.employee}",
			message="\n".join(debug_log)
		)

		return total_holiday_hours

	@frappe.whitelist()
	def get_employee_insurance_deduction(self):
		"""
		Compute employee insurance deduction
		"""
		
		if not self or not self.employee:
			return 0
				
		# Get active insurance record
		insurance_records = frappe.get_all("Employee Health Insurance",
			filters={
				"employee": self.employee,
				"is_active": 1,
				"enrolment_date": ["<=", getdate(self.end_date)]
			},
			fields=["name"],
			order_by="enrolment_date desc",
			limit=1
		)
		
		if not insurance_records:
			return 0
		
		insurance_doc = frappe.get_doc("Employee Health Insurance", insurance_records[0].name)
		
		total_deduction = insurance_doc.self_deduction + insurance_doc.dependent_deduction

		return total_deduction


	@frappe.whitelist()
	def get_employer_insurance_contribution(self):
		"""
		Get employer insurance contribution
		"""
		
		if not self or not self.employee:
			return 0
				
		# Get active insurance record
		insurance_records = frappe.get_all("Employee Health Insurance",
			filters={
				"employee": self.employee,
				"is_active": 1,
				"enrolment_date": ["<=", self.end_date]
			},
			fields=["name"],
			order_by="enrolment_date desc",
			limit=1
		)
		
		if not insurance_records:
			return 0
		
		insurance_doc = frappe.get_doc("Employee Health Insurance", insurance_records[0].name)
		
		total_contribution = insurance_doc.employer_contribution or 0
		
		return total_contribution
	
	def get_shift_datetimes(self, shift_assignment):
		"""
		Given a shift assignment, return the shift start and shift end datetimes for each day it spans.

		Args:
			shift_assignment (dict): A dictionary containing the shift assignment details.
				Expected keys: 'start_date', 'end_date', 'shift_type'

		Returns:
			list: A list of dictionaries, each containing 'shift_start' and 'shift_end' for a day.
		"""
		shift_type = frappe.get_doc("Shift Type", shift_assignment["shift_type"])
		start_time = shift_type.start_time
		end_time = shift_type.end_time

		# Convert start_date and end_date to datetime objects
		start_date = shift_assignment["start_date"]
		end_date = shift_assignment["end_date"]

		# Initialize the list to store shift datetimes
		shift_datetimes = []

		# Iterate through each day in the shift assignment
		current_date = start_date
		while current_date <= end_date:
			shift_start = datetime.strptime(f"{current_date} {start_time}", "%Y-%m-%d %H:%M:%S")

			# Handle overnight / 24-hour shifts
			if end_time <= start_time:  # Shift ends the next day
				shift_end_date = current_date + timedelta(days=1)
				shift_end = datetime.strptime(f"{shift_end_date} {end_time}", "%Y-%m-%d %H:%M:%S")
			else:
				shift_end = datetime.strptime(f"{current_date} {end_time}", "%Y-%m-%d %H:%M:%S")

			# Append the shift start and end to the list
			shift_datetimes.append({
				"shift_start": shift_start,
				"shift_end": shift_end
			})

			# Move to the next day
			current_date += timedelta(days=1)

		return shift_datetimes
	
	@frappe.whitelist()
	def get_approved_overtime_count(self, rate=None):
		"""Returns the count of approved employee overtime requests in a given date range."""
		rate_disable_map = {
			1.5: "disable_overtime_15x",
			2.0: "disable_overtime_2x",
			3.0: "disable_overtime_3x",
		}
		disable_field = rate_disable_map.get(flt(rate))
		if disable_field and self.get(disable_field):
			return 0.0
		records = frappe.db.get_all(
			"Employee Overtime",
			filters={
				"employee": self.employee,
				"rate": rate,
				"date": ["between", [self.start_date, self.end_date]],
				"workflow_state": "Approved",
				"docstatus": 1
			},
			fields={'name', 'number_of_hours'}
		)

		count = sum(r['number_of_hours'] for r in records if r['number_of_hours'])
		# Public holiday hours pay at 2.0 only when basic < Rs50k; approved OT requests always count.
		holiday_hours = 0
		if flt(rate) == 2.0:
			e_basic = flt(frappe.db.get_value("Employee", self.employee, "e_basic"))
			if e_basic < 50000:
				holiday_hours = self.get_holiday_hours()
		return float(count + holiday_hours)

	@frappe.whitelist()
	def get_employee_dept(self):
		"""Returns the department of the employee"""
		return frappe.db.get_value("Employee", self.employee, "department")
	
	def autoname(self):
		self.name = make_autoname(self.series)

	@property
	def joining_date(self):
		if not hasattr(self, "__joining_date"):
			self.__joining_date = frappe.get_cached_value(
				"Employee",
				self.employee,
				"date_of_joining",
			)

		return self.__joining_date
	
	@property
	def leaving_date(self):
		if not hasattr(self, "__leaving_date"):
			self.__joining_date = frappe.get_cached_value(
				"Employee",
				self.employee,
				"leaving_date",
			)

		return self.__joining_date

	@property
	def relieving_date(self):
		if not hasattr(self, "__relieving_date"):
			self.__relieving_date = frappe.get_cached_value(
				"Employee",
				self.employee,
				"relieving_date",
			)

		return self.__relieving_date

	@property
	def payroll_period(self):
		if not hasattr(self, "__payroll_period"):
			self.__payroll_period = get_payroll_period(self.start_date, self.end_date, self.company)

		return self.__payroll_period

	@property
	def actual_start_date(self):
		if not hasattr(self, "__actual_start_date"):
			self.__actual_start_date = self.start_date

			if self.joining_date and getdate(self.start_date) < self.joining_date <= getdate(self.end_date):
				self.__actual_start_date = self.joining_date

		return self.__actual_start_date

	@property
	def actual_end_date(self):
		if not hasattr(self, "__actual_end_date"):
			self.__actual_end_date = self.end_date

			if self.relieving_date and getdate(self.start_date) <= self.relieving_date < getdate(
				self.end_date
			):
				self.__actual_end_date = self.relieving_date

		return self.__actual_end_date

	def validate(self):
		self.status = self.get_status()
		validate_active_employee(self.employee)
		self.validate_dates()
		self.check_existing()

		if not self.salary_slip_based_on_timesheet:
			self.get_date_details()

		if not (len(self.get("earnings")) or len(self.get("deductions"))):
			# get details from salary structure
			self.get_emp_and_working_day_details()
		else:
			self.get_working_days_details(lwp=self.leave_without_pay)

		self.set_salary_structure_assignment()
		self.calculate_net_pay()
		self.compute_year_to_date()
		self.compute_month_to_date()
		self.compute_component_wise_year_to_date()

		self.add_leave_balances()

		max_working_hours = frappe.db.get_single_value(
			"Payroll Settings", "max_working_hours_against_timesheet"
		)
		if max_working_hours:
			if self.salary_slip_based_on_timesheet and (self.total_working_hours > int(max_working_hours)):
				frappe.msgprint(
					_("Total working hours should not be greater than max working hours {0}").format(
						max_working_hours
					),
					alert=True,
				)

	def set_net_total_in_words(self):
		doc_currency = self.currency
		company_currency = erpnext.get_company_currency(self.company)
		total = self.net_pay if self.is_rounding_total_disabled() else self.rounded_total
		base_total = self.base_net_pay if self.is_rounding_total_disabled() else self.base_rounded_total
		self.total_in_words = money_in_words(total, doc_currency)
		self.base_total_in_words = money_in_words(base_total, company_currency)

	def on_update(self):
		self.publish_update()

	def on_submit(self):
		if self.net_pay < 0:
			frappe.throw(_("Net Pay cannot be less than 0"))
		else:
			self.set_status()
			self.update_status(self.name)

			make_loan_repayment_entry(self)

		self.update_payment_status_for_gratuity()
		# Submitted payslips are reviewed by definition
		self.db_set("payroll_reviewed", 1, update_modified=False)
		self.payroll_reviewed = 1
		self.sync_payroll_entry_after_slip_change()

	def update_payment_status_for_gratuity(self):
		additional_salary = frappe.db.get_all(
			"Additional Salary",
			filters={
				"payroll_date": ("between", [self.start_date, self.end_date]),
				"employee": self.employee,
				"ref_doctype": "Gratuity",
				"docstatus": 1,
			},
			fields=["ref_docname", "name"],
			limit=1,
		)

		if additional_salary:
			status = "Paid" if self.docstatus == 1 else "Unpaid"
			if additional_salary[0].name in [entry.additional_salary for entry in self.earnings]:
				frappe.db.set_value("Gratuity", additional_salary[0].ref_docname, "status", status)

	def on_cancel(self):
		self.set_status()
		self.update_status()
		self.update_payment_status_for_gratuity()

		cancel_loan_repayment_entry(self)
		self.db_set("payroll_reviewed", 0, update_modified=False)
		self.payroll_reviewed = 0
		self.sync_payroll_entry_after_slip_change(reopen_if_needed=True)
		self.publish_update()

	def sync_payroll_entry_after_slip_change(self, reopen_if_needed=False):
		"""Keep Payroll Entry review/complete state in sync after submit/cancel/amend."""
		if not self.payroll_entry:
			return

		pe = frappe.get_doc("Payroll Entry", self.payroll_entry)
		pe.mark_submitted_slips_reviewed()
		pe.refresh_payslips_reviewed_flag()
		if reopen_if_needed:
			pe.reopen_if_payslips_incomplete()

	def publish_update(self):
		employee_user = frappe.db.get_value("Employee", self.employee, "user_id", cache=True)
		frappe.publish_realtime(
			event="hrms:update_salary_slips",
			message={"employee": self.employee},
			user=employee_user,
			after_commit=True,
		)

	def on_trash(self):
		from frappe.model.naming import revert_series_if_last

		revert_series_if_last(self.series, self.name)

	def get_status(self):
		if self.docstatus == 0:
			status = "Draft"
		elif self.docstatus == 1:
			status = "Submitted"
		elif self.docstatus == 2:
			status = "Cancelled"
		return status

	def validate_dates(self):
		self.validate_from_to_dates("start_date", "end_date")

		if not self.joining_date:
			frappe.throw(
				_("Please set the Date Of Joining for employee {0}").format(frappe.bold(self.employee_name))
			)

		if date_diff(self.end_date, self.joining_date) < 0:
			frappe.throw(_("Cannot create Salary Slip for Employee joining after Payroll Period"))

		if self.relieving_date and date_diff(self.relieving_date, self.start_date) < 0:
			frappe.throw(_("Cannot create Salary Slip for Employee who has left before Payroll Period"))

	def is_rounding_total_disabled(self):
		return cint(frappe.db.get_single_value("Payroll Settings", "disable_rounded_total"))

	def check_existing(self):
		if not self.salary_slip_based_on_timesheet:
			ss = frappe.qb.DocType("Salary Slip")
			query = (
				frappe.qb.from_(ss)
				.select(ss.name)
				.where(
					(ss.start_date == self.start_date)
					& (ss.end_date == self.end_date)
					& (ss.docstatus != 2)
					& (ss.employee == self.employee)
					& (ss.name != self.name)
					& (ss.is_thirteenth_month == self.is_thirteenth_month)
				)
			)

			if self.payroll_entry:
				query = query.where(ss.payroll_entry == self.payroll_entry)

			ret_exist = query.run()

			if ret_exist:
				frappe.throw(
					_("Salary Slip of employee {0} already created for this period").format(self.employee)
				)
		else:
			for data in self.timesheets:
				if frappe.db.get_value("Timesheet", data.time_sheet, "status") == "Payrolled":
					frappe.throw(
						_("Salary Slip of employee {0} already created for time sheet {1}").format(
							self.employee, data.time_sheet
						)
					)

	def get_date_details(self):
		if not self.end_date:
			date_details = get_start_end_dates(self.payroll_frequency, self.start_date or self.posting_date)
			self.start_date = date_details.start_date
			self.end_date = date_details.end_date

	@frappe.whitelist()
	def get_emp_and_working_day_details(self):
		"""First time, load all the components from salary structure"""
		if self.employee:
			self.set("earnings", [])
			self.set("deductions", [])

			if not self.salary_slip_based_on_timesheet:
				self.get_date_details()

			self.validate_dates()

			# getin leave details
			self.get_working_days_details()
			struct = self.check_sal_struct()

			if struct:
				self._salary_structure_doc = frappe.get_cached_doc("Salary Structure", struct)
				self.salary_slip_based_on_timesheet = (
					self._salary_structure_doc.salary_slip_based_on_timesheet or 0
				)
				self.set_time_sheet()
				self.pull_sal_struct()

	def set_time_sheet(self):
		if self.salary_slip_based_on_timesheet:
			self.set("timesheets", [])

			Timesheet = frappe.qb.DocType("Timesheet")
			timesheets = (
				frappe.qb.from_(Timesheet)
				.select(Timesheet.star)
				.where(
					(Timesheet.employee == self.employee)
					& (Timesheet.start_date.between(self.start_date, self.end_date))
					& ((Timesheet.status == "Submitted") | (Timesheet.status == "Billed"))
				)
			).run(as_dict=1)

			for data in timesheets:
				self.append("timesheets", {"time_sheet": data.name, "working_hours": data.total_hours})

	def check_sal_struct(self):
		ss = frappe.qb.DocType("Salary Structure")
		ssa = frappe.qb.DocType("Salary Structure Assignment")

		query = (
			frappe.qb.from_(ssa)
			.join(ss)
			.on(ssa.salary_structure == ss.name)
			.select(ssa.salary_structure)
			.where(
				(ssa.docstatus == 1)
				& (ss.docstatus == 1)
				& (ss.is_active == "Yes")
				& (ssa.employee == self.employee)
				& (
					(ssa.from_date <= self.start_date)
					| (ssa.from_date <= self.end_date)
					| (ssa.from_date <= self.joining_date)
				)
			)
			.orderby(ssa.from_date, order=Order.desc)
			.limit(1)
		)

		if not self.salary_slip_based_on_timesheet and self.payroll_frequency:
			query = query.where(ss.payroll_frequency == self.payroll_frequency)

		st_name = query.run()

		if st_name:
			self.salary_structure = st_name[0][0]
			return self.salary_structure

		else:
			self.salary_structure = None
			frappe.msgprint(
				_("No active or default Salary Structure found for employee {0} for the given dates").format(
					self.employee
				),
				title=_("Salary Structure Missing"),
			)

	def pull_sal_struct(self):
		from hrms.payroll.doctype.salary_structure.salary_structure import make_salary_slip

		if self.salary_slip_based_on_timesheet:
			self.salary_structure = self._salary_structure_doc.name
			self.hour_rate = self._salary_structure_doc.hour_rate
			self.base_hour_rate = flt(self.hour_rate) * flt(self.exchange_rate)
			self.total_working_hours = sum([d.working_hours or 0.0 for d in self.timesheets]) or 0.0
			wages_amount = self.hour_rate * self.total_working_hours

			self.add_earning_for_hourly_wages(self, self._salary_structure_doc.salary_component, wages_amount)

		make_salary_slip(self._salary_structure_doc.name, self)

	def get_working_days_details(self, lwp=None, for_preview=0):
		payroll_settings = frappe.get_cached_value(
			"Payroll Settings",
			None,
			(
				"payroll_based_on",
				"include_holidays_in_total_working_days",
				"consider_marked_attendance_on_holidays",
				"daily_wages_fraction_for_half_day",
				"consider_unmarked_attendance_as",
			),
			as_dict=1,
		)

		consider_marked_attendance_on_holidays = (
			payroll_settings.include_holidays_in_total_working_days
			and payroll_settings.consider_marked_attendance_on_holidays
		)

		daily_wages_fraction_for_half_day = flt(payroll_settings.daily_wages_fraction_for_half_day) or 0.5

		working_days = date_diff(self.end_date, self.start_date) + 1
		if for_preview:
			self.total_working_days = working_days
			self.payment_days = working_days
			return

		holidays = self.get_holidays_for_employee(self.start_date, self.end_date)
		working_days_list = [add_days(getdate(self.start_date), days=day) for day in range(0, working_days)]

		if not cint(payroll_settings.include_holidays_in_total_working_days):
			working_days_list = [i for i in working_days_list if i not in holidays]

			working_days -= len(holidays)
			if working_days < 0:
				frappe.throw(_("There are more holidays than working days this month."))

		if not payroll_settings.payroll_based_on:
			frappe.throw(_("Please set Payroll based on in Payroll settings"))

		if payroll_settings.payroll_based_on == "Attendance":
			actual_lwp, absent = self.calculate_lwp_ppl_and_absent_days_based_on_attendance(
				holidays, daily_wages_fraction_for_half_day, consider_marked_attendance_on_holidays
			)
			self.absent_days = absent
		else:
			actual_lwp = self.calculate_lwp_or_ppl_based_on_leave_application(
				holidays, working_days_list, daily_wages_fraction_for_half_day
			)

		if not lwp:
			lwp = actual_lwp
		elif lwp != actual_lwp:
			frappe.msgprint(
				_("Leave Without Pay does not match with approved {} records").format(
					payroll_settings.payroll_based_on
				)
			)

		self.leave_without_pay = lwp
		self.total_working_days = working_days

		payment_days = self.get_payment_days(payroll_settings.include_holidays_in_total_working_days)

		if flt(payment_days) > flt(lwp):
			self.payment_days = flt(payment_days) - flt(lwp)

			if payroll_settings.payroll_based_on == "Attendance":
				self.payment_days -= flt(absent)

			consider_unmarked_attendance_as = payroll_settings.consider_unmarked_attendance_as or "Present"

			if (
				payroll_settings.payroll_based_on == "Attendance"
				and consider_unmarked_attendance_as == "Absent"
			):
				unmarked_days = self.get_unmarked_days(
					payroll_settings.include_holidays_in_total_working_days, holidays
				)
				self.absent_days += unmarked_days  # will be treated as absent
				self.payment_days -= unmarked_days
		else:
			self.payment_days = 0

	def get_unmarked_days(
		self, include_holidays_in_total_working_days: bool, holidays: list | None = None
	) -> float:
		"""Calculates the number of unmarked days for an employee within a date range"""
		unmarked_days = (
			self.total_working_days
			- self._get_days_outside_period(include_holidays_in_total_working_days, holidays)
			- self._get_marked_attendance_days(holidays)
		)

		if include_holidays_in_total_working_days and holidays:
			unmarked_days -= self._get_number_of_holidays(holidays)

		return unmarked_days

	def _get_days_outside_period(
		self, include_holidays_in_total_working_days: bool, holidays: list | None = None
	):
		"""Returns days before DOJ or after relieving date"""

		def _get_days(start_date, end_date):
			no_of_days = date_diff(end_date, start_date) + 1

			if include_holidays_in_total_working_days:
				return no_of_days
			else:
				days = 0
				end_date = getdate(end_date)
				for day in range(no_of_days):
					date = add_days(end_date, -day)
					if date not in holidays:
						days += 1
				return days

		days = 0
		if self.actual_start_date != self.start_date:
			days += _get_days(self.start_date, add_days(self.joining_date, -1))

		if self.actual_end_date != self.end_date:
			days += _get_days(add_days(self.relieving_date, 1), self.end_date)

		return days

	def _get_number_of_holidays(self, holidays: list | None = None) -> float:
		no_of_holidays = 0
		actual_end_date = getdate(self.actual_end_date)

		for days in range(date_diff(self.actual_end_date, self.actual_start_date) + 1):
			date = add_days(actual_end_date, -days)
			if date in holidays:
				no_of_holidays += 1

		return no_of_holidays

	def _get_marked_attendance_days(self, holidays: list | None = None) -> float:
		Attendance = frappe.qb.DocType("Attendance")
		query = (
			frappe.qb.from_(Attendance)
			.select(Count("*"))
			.where(
				(Attendance.attendance_date.between(self.actual_start_date, self.actual_end_date))
				& (Attendance.employee == self.employee)
				& (Attendance.docstatus == 1)
			)
		)
		if holidays:
			query = query.where(Attendance.attendance_date.notin(holidays))

		return query.run()[0][0]

	def get_payment_days(self, include_holidays_in_total_working_days):
		if self.joining_date and self.joining_date > getdate(self.end_date):
			# employee joined after payroll date
			return 0

		if self.relieving_date:
			employee_status = frappe.db.get_value("Employee", self.employee, "status")
			if self.relieving_date < getdate(self.start_date) and employee_status != "Left":
				frappe.throw(_("Employee relieved on {0} must be set as 'Left'").format(self.relieving_date))

		payment_days = date_diff(self.actual_end_date, self.actual_start_date) + 1

		if not cint(include_holidays_in_total_working_days):
			holidays = self.get_holidays_for_employee(self.actual_start_date, self.actual_end_date)
			payment_days -= len(holidays)

		return payment_days

	def get_holidays_for_employee(self, start_date, end_date):
		holiday_list = get_holiday_list_for_employee(self.employee)
		key = f"{holiday_list}:{start_date}:{end_date}"
		holiday_dates = frappe.cache().hget(HOLIDAYS_BETWEEN_DATES, key)

		if not holiday_dates:
			holiday_dates = get_holiday_dates_between(holiday_list, start_date, end_date)
			frappe.cache().hset(HOLIDAYS_BETWEEN_DATES, key, holiday_dates)

		return holiday_dates

	def calculate_lwp_or_ppl_based_on_leave_application(
		self, holidays, working_days_list, daily_wages_fraction_for_half_day
	):
		lwp = 0
		leaves = get_lwp_or_ppl_for_date_range(
			self.employee,
			self.start_date,
			self.end_date,
		)

		for d in working_days_list:
			if self.relieving_date and d > self.relieving_date:
				continue

			leave = leaves.get(d)

			if not leave:
				continue

			if not leave.include_holiday and getdate(d) in holidays:
				continue

			equivalent_lwp_count = 0
			fraction_of_daily_salary_per_leave = flt(leave.fraction_of_daily_salary_per_leave)

			is_half_day_leave = False
			if cint(leave.half_day) and (leave.half_day_date == d or leave.from_date == leave.to_date):
				is_half_day_leave = True

			equivalent_lwp_count = (1 - daily_wages_fraction_for_half_day) if is_half_day_leave else 1

			if cint(leave.is_ppl):
				equivalent_lwp_count *= (
					fraction_of_daily_salary_per_leave if fraction_of_daily_salary_per_leave else 1
				)

			lwp += equivalent_lwp_count

		return lwp

	def get_leave_type_map(self) -> dict:
		"""Returns (partially paid leaves/leave without pay) leave types by name"""

		def _get_leave_type_map():
			leave_types = frappe.get_all(
				"Leave Type",
				or_filters={"is_ppl": 1, "is_lwp": 1},
				fields=["name", "is_lwp", "is_ppl", "fraction_of_daily_salary_per_leave", "include_holiday"],
			)
			return {leave_type.name: leave_type for leave_type in leave_types}

		return frappe.cache().get_value(LEAVE_TYPE_MAP, _get_leave_type_map)

	def get_employee_attendance(self, start_date, end_date):
		attendance = frappe.qb.DocType("Attendance")

		attendance_details = (
			frappe.qb.from_(attendance)
			.select(attendance.attendance_date, attendance.status, attendance.leave_type)
			.where(
				(attendance.status.isin(["Absent", "Half Day", "On Leave"]))
				& (attendance.employee == self.employee)
				& (attendance.docstatus == 1)
				& (attendance.attendance_date.between(start_date, end_date))
			)
		).run(as_dict=1)

		return attendance_details

	def calculate_lwp_ppl_and_absent_days_based_on_attendance(
		self, holidays, daily_wages_fraction_for_half_day, consider_marked_attendance_on_holidays
	):
		lwp = 0
		absent = 0

		leave_type_map = self.get_leave_type_map()
		attendance_details = self.get_employee_attendance(
			start_date=self.start_date, end_date=self.actual_end_date
		)

		for d in attendance_details:
			if (
				d.status in ("Half Day", "On Leave")
				and d.leave_type
				and d.leave_type not in leave_type_map.keys()
			):
				continue

			# skip counting absent on holidays
			if not consider_marked_attendance_on_holidays and getdate(d.attendance_date) in holidays:
				if d.status in ["Absent", "Half Day"] or (
					d.leave_type
					and d.leave_type in leave_type_map.keys()
					and not leave_type_map[d.leave_type]["include_holiday"]
				):
					continue

			if d.leave_type:
				fraction_of_daily_salary_per_leave = leave_type_map[d.leave_type][
					"fraction_of_daily_salary_per_leave"
				]

			if d.status == "Half Day":
				equivalent_lwp = 1 - daily_wages_fraction_for_half_day

				if d.leave_type in leave_type_map.keys() and leave_type_map[d.leave_type]["is_ppl"]:
					equivalent_lwp *= (
						fraction_of_daily_salary_per_leave if fraction_of_daily_salary_per_leave else 1
					)
				lwp += equivalent_lwp

			elif d.status == "On Leave" and d.leave_type and d.leave_type in leave_type_map.keys():
				equivalent_lwp = 1
				if leave_type_map[d.leave_type]["is_ppl"]:
					equivalent_lwp *= (
						fraction_of_daily_salary_per_leave if fraction_of_daily_salary_per_leave else 1
					)
				lwp += equivalent_lwp

			elif d.status == "Absent":
				absent += 1

		return lwp, absent

	def add_earning_for_hourly_wages(self, doc, salary_component, amount):
		row_exists = False
		for row in doc.earnings:
			if row.salary_component == salary_component:
				row.amount = amount
				row_exists = True
				break

		if not row_exists:
			wages_row = {
				"salary_component": salary_component,
				"abbr": frappe.db.get_value(
					"Salary Component", salary_component, "salary_component_abbr", cache=True
				),
				"amount": self.hour_rate * self.total_working_hours,
				"default_amount": 0.0,
				"additional_amount": 0.0,
			}
			doc.append("earnings", wages_row)

	def set_salary_structure_assignment(self):
		self._salary_structure_assignment = frappe.db.get_value(
			"Salary Structure Assignment",
			{
				"employee": self.employee,
				"salary_structure": self.salary_structure,
				"from_date": ("<=", self.actual_start_date),
				"docstatus": 1,
			},
			"*",
			order_by="from_date desc",
			as_dict=True,
		)

		if not self._salary_structure_assignment:
			frappe.throw(
				_(
					"Please assign a Salary Structure for Employee {0} applicable from or before {1} first"
				).format(
					frappe.bold(self.employee_name),
					frappe.bold(formatdate(self.actual_start_date)),
				)
			)

	def calculate_net_pay(self):
		if self.salary_structure:
			self.calculate_component_amounts("earnings")

		# get remaining numbers of sub-period (period for which one salary is processed)
		if self.payroll_period:
			self.remaining_sub_periods = get_period_factor(
				self.employee,
				self.start_date,
				self.end_date,
				self.payroll_frequency,
				self.payroll_period,
				joining_date=self.joining_date,
				relieving_date=self.relieving_date,
			)[1]

		self.gross_pay = self.get_component_totals("earnings", depends_on_payment_days=1)
		self.base_gross_pay = flt(
			flt(self.gross_pay) * flt(self.exchange_rate), self.precision("base_gross_pay")
		)

		if self.salary_structure:
			self.calculate_component_amounts("deductions")

		set_loan_repayment(self)

		self.set_precision_for_component_amounts()
		self.set_net_pay()
		self.compute_income_tax_breakup()

	def set_net_pay(self):
		self.total_deduction = self.get_component_totals("deductions")
		self.base_total_deduction = flt(
			flt(self.total_deduction) * flt(self.exchange_rate), self.precision("base_total_deduction")
		)
		self.net_pay = flt(self.gross_pay) - (
			flt(self.total_deduction) + flt(self.get("total_loan_repayment"))
		)
		self.rounded_total = rounded(self.net_pay)
		self.base_net_pay = flt(flt(self.net_pay) * flt(self.exchange_rate), self.precision("base_net_pay"))
		self.base_rounded_total = flt(rounded(self.base_net_pay), self.precision("base_net_pay"))
		if self.hour_rate:
			self.base_hour_rate = flt(
				flt(self.hour_rate) * flt(self.exchange_rate), self.precision("base_hour_rate")
			)
		self.set_net_total_in_words()

	def compute_taxable_earnings_for_year(self):
		# get taxable_earnings, opening_taxable_earning, paid_taxes for previous period
		self.previous_taxable_earnings, exempted_amount = self.get_taxable_earnings_for_prev_period(
			self.payroll_period.start_date, self.start_date, self.tax_slab.allow_tax_exemption
		)

		self.previous_taxable_earnings_before_exemption = self.previous_taxable_earnings + exempted_amount

		self.compute_current_and_future_taxable_earnings()

		# Deduct taxes forcefully for unsubmitted tax exemption proof and unclaimed benefits in the last period
		if self.payroll_period.end_date <= getdate(self.end_date):
			self.deduct_tax_for_unsubmitted_tax_exemption_proof = 1
			self.deduct_tax_for_unclaimed_employee_benefits = 1

		# Get taxable unclaimed benefits
		self.unclaimed_taxable_benefits = 0
		if self.deduct_tax_for_unclaimed_employee_benefits:
			self.unclaimed_taxable_benefits = self.calculate_unclaimed_taxable_benefits()

		# Total exemption amount based on tax exemption declaration
		self.total_exemption_amount = self.get_total_exemption_amount()

		# Employee Other Incomes
		self.other_incomes = self.get_income_form_other_sources() or 0.0

		# Total taxable earnings including additional and other incomes
		self.total_taxable_earnings = (
			self.previous_taxable_earnings
			+ self.current_structured_taxable_earnings
			+ self.future_structured_taxable_earnings
			+ self.current_additional_earnings
			+ self.other_incomes
			+ self.unclaimed_taxable_benefits
			- self.total_exemption_amount
		)

		# Total taxable earnings without additional earnings with full tax
		self.total_taxable_earnings_without_full_tax_addl_components = (
			self.total_taxable_earnings - self.current_additional_earnings_with_full_tax
		)

	def compute_current_and_future_taxable_earnings(self):
		# get taxable_earnings for current period (all days)
		self.current_taxable_earnings = self.get_taxable_earnings(self.tax_slab.allow_tax_exemption)
		self.future_structured_taxable_earnings = self.current_taxable_earnings.taxable_earnings * (
			ceil(self.remaining_sub_periods) - 1
		)

		current_taxable_earnings_before_exemption = (
			self.current_taxable_earnings.taxable_earnings
			+ self.current_taxable_earnings.amount_exempted_from_income_tax
		)
		self.future_structured_taxable_earnings_before_exemption = (
			current_taxable_earnings_before_exemption * (ceil(self.remaining_sub_periods) - 1)
		)

		# get taxable_earnings, addition_earnings for current actual payment days
		self.current_taxable_earnings_for_payment_days = self.get_taxable_earnings(
			self.tax_slab.allow_tax_exemption, based_on_payment_days=1
		)

		self.current_structured_taxable_earnings = (
			self.current_taxable_earnings_for_payment_days.taxable_earnings
		)
		self.current_structured_taxable_earnings_before_exemption = (
			self.current_structured_taxable_earnings
			+ self.current_taxable_earnings_for_payment_days.amount_exempted_from_income_tax
		)

		self.current_additional_earnings = self.current_taxable_earnings_for_payment_days.additional_income

		self.current_additional_earnings_with_full_tax = (
			self.current_taxable_earnings_for_payment_days.additional_income_with_full_tax
		)

	def compute_income_tax_breakup(self):
		if not self.payroll_period:
			return

		self.standard_tax_exemption_amount = 0
		self.tax_exemption_declaration = 0
		self.deductions_before_tax_calculation = 0

		self.non_taxable_earnings = self.compute_non_taxable_earnings()

		self.ctc = self.compute_ctc()

		self.income_from_other_sources = self.get_income_form_other_sources()

		self.total_earnings = self.ctc + self.income_from_other_sources

		if hasattr(self, "tax_slab"):
			if self.tax_slab.allow_tax_exemption:
				self.standard_tax_exemption_amount = self.tax_slab.standard_tax_exemption_amount
				self.deductions_before_tax_calculation = (
					self.compute_annual_deductions_before_tax_calculation()
				)

			self.tax_exemption_declaration = (
				self.get_total_exemption_amount() - self.standard_tax_exemption_amount
			)

		self.annual_taxable_amount = self.total_earnings - (
			self.non_taxable_earnings
			+ self.deductions_before_tax_calculation
			+ self.tax_exemption_declaration
			+ self.standard_tax_exemption_amount
		)

		self.income_tax_deducted_till_date = self.get_income_tax_deducted_till_date()

		if hasattr(self, "total_structured_tax_amount") and hasattr(self, "current_structured_tax_amount"):
			self.future_income_tax_deductions = (
				self.total_structured_tax_amount - self.income_tax_deducted_till_date
			)

			self.current_month_income_tax = self.current_structured_tax_amount

			# non included current_month_income_tax separately as its already considered
			# while calculating income_tax_deducted_till_date

			self.total_income_tax = self.income_tax_deducted_till_date + self.future_income_tax_deductions

	def compute_ctc(self):
		if hasattr(self, "previous_taxable_earnings"):
			return (
				self.previous_taxable_earnings_before_exemption
				+ self.current_structured_taxable_earnings_before_exemption
				+ self.future_structured_taxable_earnings_before_exemption
				+ self.current_additional_earnings
				+ self.other_incomes
				+ self.unclaimed_taxable_benefits
				+ self.non_taxable_earnings
			)

		return 0.0

	def compute_non_taxable_earnings(self):
		# Previous period non taxable earnings
		prev_period_non_taxable_earnings = self.get_salary_slip_details(
			self.payroll_period.start_date, self.start_date, parentfield="earnings", is_tax_applicable=0
		)

		(
			current_period_non_taxable_earnings,
			non_taxable_additional_salary,
		) = self.get_non_taxable_earnings_for_current_period()

		# Future period non taxable earnings
		future_period_non_taxable_earnings = current_period_non_taxable_earnings * (
			ceil(self.remaining_sub_periods) - 1
		)

		non_taxable_earnings = (
			prev_period_non_taxable_earnings
			+ current_period_non_taxable_earnings
			+ future_period_non_taxable_earnings
			+ non_taxable_additional_salary
		)

		return non_taxable_earnings

	def get_non_taxable_earnings_for_current_period(self):
		current_period_non_taxable_earnings = 0.0

		non_taxable_additional_salary = self.get_salary_slip_details(
			self.payroll_period.start_date,
			self.start_date,
			parentfield="earnings",
			is_tax_applicable=0,
			field_to_select="additional_amount",
		)

		# Current period non taxable earnings
		for earning in self.earnings:
			if earning.is_tax_applicable:
				continue

			if earning.additional_amount:
				non_taxable_additional_salary += earning.additional_amount

				# Future recurring additional salary
				if earning.additional_salary and earning.is_recurring_additional_salary:
					non_taxable_additional_salary += self.get_future_recurring_additional_amount(
						earning.additional_salary, earning.additional_amount
					)
			else:
				current_period_non_taxable_earnings += earning.amount

		return current_period_non_taxable_earnings, non_taxable_additional_salary

	def compute_annual_deductions_before_tax_calculation(self):
		prev_period_exempted_amount = 0
		current_period_exempted_amount = 0
		future_period_exempted_amount = 0

		# Previous period exempted amount
		prev_period_exempted_amount = self.get_salary_slip_details(
			self.payroll_period.start_date,
			self.start_date,
			parentfield="deductions",
			exempted_from_income_tax=1,
		)

		# Current period exempted amount
		for d in self.get("deductions"):
			if d.exempted_from_income_tax:
				current_period_exempted_amount += d.amount

		# Future period exempted amount
		for deduction in self._salary_structure_doc.get("deductions"):
			if deduction.exempted_from_income_tax:
				if deduction.amount_based_on_formula:
					for sub_period in range(1, ceil(self.remaining_sub_periods)):
						future_period_exempted_amount += self.get_amount_from_formula(deduction, sub_period)
				else:
					future_period_exempted_amount += deduction.amount * (ceil(self.remaining_sub_periods) - 1)

		return (
			prev_period_exempted_amount + current_period_exempted_amount + future_period_exempted_amount
		) or 0

	def get_amount_from_formula(self, struct_row, sub_period=1):
		if self.payroll_frequency == "Monthly":
			start_date = frappe.utils.add_months(self.start_date, sub_period)
			end_date = frappe.utils.add_months(self.end_date, sub_period)
			posting_date = frappe.utils.add_months(self.posting_date, sub_period)

		else:
			days_to_add = 0
			if self.payroll_frequency == "Weekly":
				days_to_add = sub_period * 6

			if self.payroll_frequency == "Fortnightly":
				days_to_add = sub_period * 13

			if self.payroll_frequency == "Daily":
				days_to_add = start_date

			start_date = frappe.utils.add_days(self.start_date, days_to_add)
			end_date = frappe.utils.add_days(self.end_date, days_to_add)
			posting_date = start_date

		local_data = self.data.copy()
		local_data.update({"start_date": start_date, "end_date": end_date, "posting_date": posting_date})

		return flt(self.eval_condition_and_formula(struct_row, local_data))

	def get_income_tax_deducted_till_date(self):
		tax_deducted = 0.0
		for tax_component in self.get("_component_based_variable_tax") or {}:
			tax_deducted += (
				self._component_based_variable_tax[tax_component]["previous_total_paid_taxes"]
				+ self._component_based_variable_tax[tax_component]["current_tax_amount"]
			)
		return tax_deducted

	def calculate_component_amounts(self, component_type):
		if not getattr(self, "_salary_structure_doc", None):
			self._salary_structure_doc = frappe.get_cached_doc("Salary Structure", self.salary_structure)

		self.add_structure_components(component_type)
		self.add_additional_salary_components(component_type)
		if component_type == "earnings":
			self.add_employee_benefits()
		else:
			self.add_tax_components()

	def add_structure_components(self, component_type):
		self.data, self.default_data = self.get_data_for_eval()
		timesheet_component = self._salary_structure_doc.salary_component

		for struct_row in self._salary_structure_doc.get(component_type):
			if self.salary_slip_based_on_timesheet and struct_row.salary_component == timesheet_component:
				continue

			amount = self.eval_condition_and_formula(struct_row, self.data)
			if struct_row.statistical_component:
				# update statitical component amount in reference data based on payment days
				# since row for statistical component is not added to salary slip

				self.default_data[struct_row.abbr] = flt(amount)
				if struct_row.depends_on_payment_days:
					payment_days_amount = (
						flt(amount) * flt(self.payment_days) / cint(self.total_working_days)
						if self.total_working_days
						else 0
					)
					self.data[struct_row.abbr] = flt(payment_days_amount, struct_row.precision("amount"))

			else:
				# default behavior, the system does not add if component amount is zero
				# if remove_if_zero_valued is unchecked, then ask system to add component row
				remove_if_zero_valued = frappe.get_cached_value(
					"Salary Component", struct_row.salary_component, "remove_if_zero_valued"
				)

				default_amount = 0

				if (
					amount
					or (struct_row.amount_based_on_formula and amount is not None)
					or (not remove_if_zero_valued and amount is not None and not self.data[struct_row.abbr])
				):
					default_amount = self.eval_condition_and_formula(struct_row, self.default_data)
					self.update_component_row(
						struct_row,
						amount,
						component_type,
						data=self.data,
						default_amount=default_amount,
						remove_if_zero_valued=remove_if_zero_valued,
					)

	def get_data_for_eval(self):
		"""Returns data for evaluating formula"""
		data = frappe._dict()
		employee = frappe.get_cached_doc("Employee", self.employee).as_dict()

		if not hasattr(self, "_salary_structure_assignment"):
			self.set_salary_structure_assignment()

		data.update(self._salary_structure_assignment)
		data.update(self.as_dict())
		data.update(employee)

		data.update(self.get_component_abbr_map())

		# shallow copy of data to store default amounts (without payment days) for tax calculation
		default_data = data.copy()

		for key in ("earnings", "deductions"):
			for d in self.get(key):
				default_data[d.abbr] = d.default_amount or 0
				data[d.abbr] = d.amount or 0

		return data, default_data

	def get_component_abbr_map(self):
		def _fetch_component_values():
			return {
				component_abbr: 0
				for component_abbr in frappe.get_all("Salary Component", pluck="salary_component_abbr")
			}

		return frappe.cache().get_value(SALARY_COMPONENT_VALUES, generator=_fetch_component_values)

	def eval_condition_and_formula(self, struct_row, data):
		try:
			condition = sanitize_expression(struct_row.condition)
			if condition:
				if not _safe_eval(condition, self.whitelisted_globals, data):
					return None
			amount = struct_row.amount
			if struct_row.amount_based_on_formula:
				formula = sanitize_expression(struct_row.formula)
				if formula:
					amount = flt(
						_safe_eval(formula, self.whitelisted_globals, data), struct_row.precision("amount")
					)
			if amount:
				data[struct_row.abbr] = amount

			return amount

		except NameError as ne:
			throw_error_message(
				struct_row,
				ne,
				title=_("Name error"),
				description=_("This error can be due to missing or deleted field."),
			)
		except SyntaxError as se:
			throw_error_message(
				struct_row,
				se,
				title=_("Syntax error"),
				description=_("This error can be due to invalid syntax."),
			)
		except Exception as exc:
			throw_error_message(
				struct_row,
				exc,
				title=_("Error in formula or condition"),
				description=_("This error can be due to invalid formula or condition."),
			)
			raise

	def add_employee_benefits(self):
		for struct_row in self._salary_structure_doc.get("earnings"):
			if struct_row.is_flexible_benefit == 1:
				if (
					frappe.db.get_value(
						"Salary Component",
						struct_row.salary_component,
						"pay_against_benefit_claim",
						cache=True,
					)
					!= 1
				):
					benefit_component_amount = get_benefit_component_amount(
						self.employee,
						self.start_date,
						self.end_date,
						struct_row.salary_component,
						self._salary_structure_doc,
						self.payroll_frequency,
						self.payroll_period,
					)
					if benefit_component_amount:
						self.update_component_row(struct_row, benefit_component_amount, "earnings")
				else:
					benefit_claim_amount = get_benefit_claim_amount(
						self.employee, self.start_date, self.end_date, struct_row.salary_component
					)
					if benefit_claim_amount:
						self.update_component_row(struct_row, benefit_claim_amount, "earnings")

		self.adjust_benefits_in_last_payroll_period(self.payroll_period)

	def adjust_benefits_in_last_payroll_period(self, payroll_period):
		if payroll_period:
			if getdate(payroll_period.end_date) <= getdate(self.end_date):
				last_benefits = get_last_payroll_period_benefits(
					self.employee, self.start_date, self.end_date, payroll_period, self._salary_structure_doc
				)
				if last_benefits:
					for last_benefit in last_benefits:
						last_benefit = frappe._dict(last_benefit)
						amount = last_benefit.amount
						self.update_component_row(frappe._dict(last_benefit.struct_row), amount, "earnings")

	def add_additional_salary_components(self, component_type):
		additional_salaries = get_additional_salaries(
			self.employee, self.start_date, self.end_date, component_type
		)

		for additional_salary in additional_salaries:
			self.update_component_row(
				get_salary_component_data(additional_salary.component),
				additional_salary.amount,
				component_type,
				additional_salary,
				is_recurring=additional_salary.is_recurring,
			)

	def add_tax_components(self):
		# Calculate variable_based_on_taxable_salary after all components updated in salary slip
		tax_components, self.other_deduction_components = [], []
		for d in self._salary_structure_doc.get("deductions"):
			if d.variable_based_on_taxable_salary == 1 and not d.formula and not flt(d.amount):
				tax_components.append(d.salary_component)
			else:
				self.other_deduction_components.append(d.salary_component)

		if self.handle_additional_salary_tax_component():
			return

		# consider manually added tax component
		if not tax_components:
			tax_components = [
				d.salary_component for d in self.get("deductions") if d.variable_based_on_taxable_salary
			]

		if self.is_new() and not tax_components:
			tax_components = self.get_tax_components()
			frappe.msgprint(
				_(
					"Added tax components from the Salary Component master as the salary structure didn't have any tax component."
				),
				indicator="blue",
				alert=True,
			)

		if tax_components and self.payroll_period and self.salary_structure:
			self.tax_slab = self.get_income_tax_slabs()
			self.compute_taxable_earnings_for_year()

		self._component_based_variable_tax = {}
		for d in tax_components:
			self._component_based_variable_tax.setdefault(d, {})
			tax_amount = self.calculate_variable_based_on_taxable_salary(d)
			tax_row = get_salary_component_data(d)
			self.update_component_row(tax_row, tax_amount, "deductions")

	def get_tax_components(self) -> list:
		"""
		Returns:
		        list: A list of tax components specific to the company.
		        If no tax components are defined for the company,
		        it returns the default tax components.
		"""
		tax_components = frappe.cache().get_value(
			TAX_COMPONENTS_BY_COMPANY, self._fetch_tax_components_by_company
		)

		default_tax_components = tax_components.get("default", [])
		return tax_components.get(self.company, default_tax_components)

	def _fetch_tax_components_by_company(self) -> dict:
		"""
		Returns:
		    dict: A dictionary containing tax components grouped by company.

		Raises:
		    None
		"""

		tax_components = {}
		sc = frappe.qb.DocType("Salary Component")
		sca = frappe.qb.DocType("Salary Component Account")

		components = (
			frappe.qb.from_(sc)
			.left_join(sca)
			.on(sca.parent == sc.name)
			.select(
				sc.name,
				sca.company,
			)
			.where(sc.variable_based_on_taxable_salary == 1)
		).run(as_dict=True)

		for component in components:
			key = component.company or "default"
			tax_components.setdefault(key, [])
			tax_components[key].append(component.name)

		return tax_components

	def handle_additional_salary_tax_component(self) -> bool:
		component = next(
			(d for d in self.get("deductions") if d.variable_based_on_taxable_salary and d.additional_salary),
			None,
		)

		if not component:
			return False

		if frappe.db.get_value(
			"Additional Salary", component.additional_salary, "overwrite_salary_structure_amount"
		):
			return True
		else:
			# overwriting disabled, remove addtional salary tax component
			self.get("deductions", []).remove(component)
			return False

	def update_component_row(
		self,
		component_data,
		amount,
		component_type,
		additional_salary=None,
		is_recurring=0,
		data=None,
		default_amount=None,
		remove_if_zero_valued=None,
	):
		component_row = None
		for d in self.get(component_type):
			if d.salary_component != component_data.salary_component:
				continue

			if (not d.additional_salary and (not additional_salary or additional_salary.overwrite)) or (
				additional_salary and additional_salary.name == d.additional_salary
			):
				component_row = d
				break

		if additional_salary and additional_salary.overwrite:
			# Additional Salary with overwrite checked, remove default rows of same component
			self.set(
				component_type,
				[
					d
					for d in self.get(component_type)
					if d.salary_component != component_data.salary_component
					or (d.additional_salary and additional_salary.name != d.additional_salary)
					or d == component_row
				],
			)

		if not component_row:
			if not (amount or default_amount) and remove_if_zero_valued:
				return

			component_row = self.append(component_type)
			for attr in (
				"depends_on_payment_days",
				"salary_component",
				"abbr",
				"do_not_include_in_total",
				"is_tax_applicable",
				"is_flexible_benefit",
				"variable_based_on_taxable_salary",
				"exempted_from_income_tax",
			):
				component_row.set(attr, component_data.get(attr))

		if additional_salary:
			if additional_salary.overwrite:
				component_row.additional_amount = flt(
					flt(amount) - flt(component_row.get("default_amount", 0)),
					component_row.precision("additional_amount"),
				)
			else:
				component_row.default_amount = 0
				component_row.additional_amount = amount

			component_row.is_recurring_additional_salary = is_recurring
			component_row.additional_salary = additional_salary.name
			component_row.deduct_full_tax_on_selected_payroll_date = (
				additional_salary.deduct_full_tax_on_selected_payroll_date
			)
		else:
			component_row.default_amount = default_amount or amount
			component_row.additional_amount = 0
			component_row.deduct_full_tax_on_selected_payroll_date = (
				component_data.deduct_full_tax_on_selected_payroll_date
			)

		component_row.amount = amount

		self.update_component_amount_based_on_payment_days(component_row, remove_if_zero_valued)

		if data:
			data[component_row.abbr] = component_row.amount

	def update_component_amount_based_on_payment_days(self, component_row, remove_if_zero_valued=None):
		component_row.amount = self.get_amount_based_on_payment_days(component_row)[0]

		# remove 0 valued components that have been updated later
		if component_row.amount == 0 and remove_if_zero_valued:
			self.remove(component_row)

	def set_precision_for_component_amounts(self):
		for component_type in ("earnings", "deductions"):
			for component_row in self.get(component_type):
				component_row.amount = flt(component_row.amount, component_row.precision("amount"))

	def calculate_variable_based_on_taxable_salary(self, tax_component):
		if not self.payroll_period:
			frappe.msgprint(
				_("Start and end dates not in a valid Payroll Period, cannot calculate {0}.").format(
					tax_component
				)
			)
			return

		return self.calculate_variable_tax(tax_component)

	def calculate_variable_tax(self, tax_component):
		self.previous_total_paid_taxes = self.get_tax_paid_in_period(
			self.payroll_period.start_date, self.start_date, tax_component
		)

		# Structured tax amount
		eval_locals, default_data = self.get_data_for_eval()
		self.total_structured_tax_amount = calculate_tax_by_tax_slab(
			self.total_taxable_earnings_without_full_tax_addl_components,
			self.tax_slab,
			self.whitelisted_globals,
			eval_locals,
		)

		self.current_structured_tax_amount = (
			self.total_structured_tax_amount - self.previous_total_paid_taxes
		) / self.remaining_sub_periods

		# Total taxable earnings with additional earnings with full tax
		self.full_tax_on_additional_earnings = 0.0
		if self.current_additional_earnings_with_full_tax:
			self.total_tax_amount = calculate_tax_by_tax_slab(
				self.total_taxable_earnings, self.tax_slab, self.whitelisted_globals, eval_locals
			)
			self.full_tax_on_additional_earnings = self.total_tax_amount - self.total_structured_tax_amount

		current_tax_amount = self.current_structured_tax_amount + self.full_tax_on_additional_earnings
		if flt(current_tax_amount) < 0:
			current_tax_amount = 0

		self._component_based_variable_tax[tax_component].update(
			{
				"previous_total_paid_taxes": self.previous_total_paid_taxes,
				"total_structured_tax_amount": self.total_structured_tax_amount,
				"current_structured_tax_amount": self.current_structured_tax_amount,
				"full_tax_on_additional_earnings": self.full_tax_on_additional_earnings,
				"current_tax_amount": current_tax_amount,
			}
		)

		return current_tax_amount

	def get_income_tax_slabs(self):
		income_tax_slab = self._salary_structure_assignment.income_tax_slab

		if not income_tax_slab:
			frappe.throw(
				_("Income Tax Slab not set in Salary Structure Assignment: {0}").format(
					get_link_to_form("Salary Structure Assignment", self._salary_structure_assignment.name)
				),
				title=_("Missing Tax Slab"),
			)

		income_tax_slab_doc = frappe.get_cached_doc("Income Tax Slab", income_tax_slab)
		if income_tax_slab_doc.disabled:
			frappe.throw(_("Income Tax Slab: {0} is disabled").format(income_tax_slab))

		if getdate(income_tax_slab_doc.effective_from) > getdate(self.payroll_period.start_date):
			frappe.throw(
				_("Income Tax Slab must be effective on or before Payroll Period Start Date: {0}").format(
					self.payroll_period.start_date
				)
			)

		return income_tax_slab_doc

	def get_taxable_earnings_for_prev_period(self, start_date, end_date, allow_tax_exemption=False):
		exempted_amount = 0
		taxable_earnings = self.get_salary_slip_details(
			start_date, end_date, parentfield="earnings", is_tax_applicable=1
		)

		if allow_tax_exemption:
			exempted_amount = self.get_salary_slip_details(
				start_date, end_date, parentfield="deductions", exempted_from_income_tax=1
			)

		opening_taxable_earning = self.get_opening_for("taxable_earnings_till_date", start_date, end_date)

		return (taxable_earnings + opening_taxable_earning) - exempted_amount, exempted_amount

	def get_opening_for(self, field_to_select, start_date, end_date):
		return self._salary_structure_assignment.get(field_to_select) or 0

	def get_salary_slip_details(
		self,
		start_date,
		end_date,
		parentfield,
		salary_component=None,
		is_tax_applicable=None,
		is_flexible_benefit=0,
		exempted_from_income_tax=0,
		variable_based_on_taxable_salary=0,
		field_to_select="amount",
	):
		ss = frappe.qb.DocType("Salary Slip")
		sd = frappe.qb.DocType("Salary Detail")

		if field_to_select == "amount":
			field = sd.amount
		else:
			field = sd.additional_amount

		query = (
			frappe.qb.from_(ss)
			.join(sd)
			.on(sd.parent == ss.name)
			.select(Sum(field))
			.where(sd.parentfield == parentfield)
			.where(sd.is_flexible_benefit == is_flexible_benefit)
			.where(ss.docstatus == 1)
			.where(ss.employee == self.employee)
			.where(ss.start_date.between(start_date, end_date))
			.where(ss.end_date.between(start_date, end_date))
		)

		if is_tax_applicable is not None:
			query = query.where(sd.is_tax_applicable == is_tax_applicable)

		if exempted_from_income_tax:
			query = query.where(sd.exempted_from_income_tax == exempted_from_income_tax)

		if variable_based_on_taxable_salary:
			query = query.where(sd.variable_based_on_taxable_salary == variable_based_on_taxable_salary)

		if salary_component:
			query = query.where(sd.salary_component == salary_component)

		result = query.run()

		return flt(result[0][0]) if result else 0.0

	def get_tax_paid_in_period(self, start_date, end_date, tax_component):
		# find total_tax_paid, tax paid for benefit, additional_salary
		total_tax_paid = self.get_salary_slip_details(
			start_date,
			end_date,
			parentfield="deductions",
			salary_component=tax_component,
			variable_based_on_taxable_salary=1,
		)

		tax_deducted_till_date = self.get_opening_for("tax_deducted_till_date", start_date, end_date)

		return total_tax_paid + tax_deducted_till_date

	def get_taxable_earnings(self, allow_tax_exemption=False, based_on_payment_days=0):
		taxable_earnings = 0
		additional_income = 0
		additional_income_with_full_tax = 0
		flexi_benefits = 0
		amount_exempted_from_income_tax = 0

		for earning in self.earnings:
			if based_on_payment_days:
				amount, additional_amount = self.get_amount_based_on_payment_days(earning)
			else:
				if earning.additional_amount:
					amount, additional_amount = earning.amount, earning.additional_amount
				else:
					amount, additional_amount = earning.default_amount, earning.additional_amount

			if earning.is_tax_applicable:
				if earning.is_flexible_benefit:
					flexi_benefits += amount
				else:
					taxable_earnings += amount - additional_amount
					additional_income += additional_amount

					# Get additional amount based on future recurring additional salary
					if additional_amount and earning.is_recurring_additional_salary:
						additional_income += self.get_future_recurring_additional_amount(
							earning.additional_salary, earning.additional_amount
						)  # Used earning.additional_amount to consider the amount for the full month

					if earning.deduct_full_tax_on_selected_payroll_date:
						additional_income_with_full_tax += additional_amount

		if allow_tax_exemption:
			for ded in self.deductions:
				if ded.exempted_from_income_tax:
					amount, additional_amount = ded.amount, ded.additional_amount
					if based_on_payment_days:
						amount, additional_amount = self.get_amount_based_on_payment_days(ded)

					taxable_earnings -= flt(amount - additional_amount)
					additional_income -= additional_amount
					amount_exempted_from_income_tax = flt(amount - additional_amount)

					if additional_amount and ded.is_recurring_additional_salary:
						additional_income -= self.get_future_recurring_additional_amount(
							ded.additional_salary, ded.additional_amount
						)  # Used ded.additional_amount to consider the amount for the full month

		return frappe._dict(
			{
				"taxable_earnings": taxable_earnings,
				"additional_income": additional_income,
				"amount_exempted_from_income_tax": amount_exempted_from_income_tax,
				"additional_income_with_full_tax": additional_income_with_full_tax,
				"flexi_benefits": flexi_benefits,
			}
		)

	def get_future_recurring_period(
		self,
		additional_salary,
	):
		to_date = None

		if self.relieving_date:
			to_date = self.relieving_date

		if not to_date:
			to_date = frappe.db.get_value("Additional Salary", additional_salary, "to_date", cache=True)

		# future month count excluding current
		from_date, to_date = getdate(self.start_date), getdate(to_date)

		# If recurring period end date is beyond the payroll period,
		# last day of payroll period should be considered for recurring period calculation
		if getdate(to_date) > getdate(self.payroll_period.end_date):
			to_date = getdate(self.payroll_period.end_date)

		future_recurring_period = ((to_date.year - from_date.year) * 12) + (to_date.month - from_date.month)

		return future_recurring_period

	def get_future_recurring_additional_amount(self, additional_salary, monthly_additional_amount):
		future_recurring_additional_amount = 0

		future_recurring_period = self.get_future_recurring_period(additional_salary)

		if future_recurring_period > 0:
			future_recurring_additional_amount = (
				monthly_additional_amount * future_recurring_period
			)  # Used earning.additional_amount to consider the amount for the full month
		return future_recurring_additional_amount

	def get_amount_based_on_payment_days(self, row):
		amount, additional_amount = row.amount, row.additional_amount
		# Leave Encashment is a one-time fixed amount from Additional Salary - do not prorate by payment_days
		if row.additional_salary:
			ref_doctype = frappe.db.get_value(
				"Additional Salary", row.additional_salary, "ref_doctype", cache=True
			)
			if ref_doctype == "Leave Encashment":
				amount = flt(row.default_amount) + flt(row.additional_amount)
				if frappe.db.get_value(
					"Salary Component", row.salary_component, "round_to_the_nearest_integer", cache=True
				):
					amount = rounded(amount or 0)
				return amount, flt(row.additional_amount)

		timesheet_component = self._salary_structure_doc.salary_component

		if (
			self.salary_structure
			and cint(row.depends_on_payment_days)
			and cint(self.total_working_days)
			and not (
				row.additional_salary and row.default_amount
			)  # to identify overwritten additional salary
			and (
				row.salary_component != timesheet_component
				or getdate(self.start_date) < self.joining_date
				or (self.relieving_date and getdate(self.end_date) > self.relieving_date)
			)
		):
			additional_amount = flt(
				(flt(row.additional_amount) * flt(self.payment_days) / cint(self.total_working_days)),
				row.precision("additional_amount"),
			)
			amount = (
				flt(
					(flt(row.default_amount) * flt(self.payment_days) / cint(self.total_working_days)),
					row.precision("amount"),
				)
				+ additional_amount
			)

		elif (
			not self.payment_days
			and row.salary_component != timesheet_component
			and cint(row.depends_on_payment_days)
		):
			amount, additional_amount = 0, 0
		elif not row.amount:
			amount = flt(row.default_amount) + flt(row.additional_amount)

		# apply rounding
		if frappe.db.get_value(
			"Salary Component", row.salary_component, "round_to_the_nearest_integer", cache=True
		):
			amount, additional_amount = rounded(amount or 0), rounded(additional_amount or 0)

		return amount, additional_amount

	def calculate_unclaimed_taxable_benefits(self):
		# get total sum of benefits paid
		total_benefits_paid = self.get_salary_slip_details(
			self.payroll_period.start_date,
			self.start_date,
			parentfield="earnings",
			is_tax_applicable=1,
			is_flexible_benefit=1,
		)

		# get total benefits claimed
		BenefitClaim = frappe.qb.DocType("Employee Benefit Claim")
		total_benefits_claimed = (
			frappe.qb.from_(BenefitClaim)
			.select(Sum(BenefitClaim.claimed_amount))
			.where(
				(BenefitClaim.docstatus == 1)
				& (BenefitClaim.employee == self.employee)
				& (BenefitClaim.claim_date.between(self.payroll_period.start_date, self.end_date))
			)
		).run()
		total_benefits_claimed = flt(total_benefits_claimed[0][0]) if total_benefits_claimed else 0

		unclaimed_taxable_benefits = (
			total_benefits_paid - total_benefits_claimed
		) + self.current_taxable_earnings_for_payment_days.flexi_benefits
		return unclaimed_taxable_benefits

	def get_total_exemption_amount(self):
		total_exemption_amount = 0
		if self.tax_slab.allow_tax_exemption:
			if self.deduct_tax_for_unsubmitted_tax_exemption_proof:
				exemption_proof = frappe.db.get_value(
					"Employee Tax Exemption Proof Submission",
					{"employee": self.employee, "payroll_period": self.payroll_period.name, "docstatus": 1},
					"exemption_amount",
					cache=True,
				)
				if exemption_proof:
					total_exemption_amount = exemption_proof
			else:
				declaration = frappe.db.get_value(
					"Employee Tax Exemption Declaration",
					{"employee": self.employee, "payroll_period": self.payroll_period.name, "docstatus": 1},
					"total_exemption_amount",
					cache=True,
				)
				if declaration:
					total_exemption_amount = declaration

		if self.tax_slab.standard_tax_exemption_amount:
			total_exemption_amount += flt(self.tax_slab.standard_tax_exemption_amount)

		return total_exemption_amount

	def get_income_form_other_sources(self):
		return (
			frappe.get_all(
				"Employee Other Income",
				filters={
					"employee": self.employee,
					"payroll_period": self.payroll_period.name,
					"company": self.company,
					"docstatus": 1,
				},
				fields="SUM(amount) as total_amount",
			)[0].total_amount
			or 0.0
		)

	def get_component_totals(self, component_type, depends_on_payment_days=0):
		total = 0.0
		for d in self.get(component_type):
			if not d.do_not_include_in_total:
				if depends_on_payment_days:
					amount = self.get_amount_based_on_payment_days(d)[0]
				else:
					amount = flt(d.amount, d.precision("amount"))
				total += amount
		return total

	@frappe.whitelist()
	def email_salary_slip(self):
		receiver = frappe.db.get_value("Employee", self.employee, "prefered_email", cache=True)
		payroll_settings = frappe.get_single("Payroll Settings")

		subject = f"Salary Slip - from {self.start_date} to {self.end_date}"
		message = _("Please see attachment")
		if payroll_settings.email_template:
			email_template = frappe.get_doc("Email Template", payroll_settings.email_template)
			context = self.as_dict()
			subject = frappe.render_template(email_template.subject, context)
			message = frappe.render_template(email_template.response, context)

		password = None
		if payroll_settings.encrypt_salary_slips_in_emails:
			password = generate_password_for_pdf(payroll_settings.password_policy, self.employee)
			if not payroll_settings.email_template:
				message += "<br>" + _(
					"Note: Your salary slip is password protected, the password to unlock the PDF is of the format {0}."
				).format(payroll_settings.password_policy)

		if receiver:
			# Try to generate PDF attachment
			attachments = []
			try:
				attachments.append(
					frappe.attach_print(self.doctype, self.name, file_name=self.name, password=password)
				)
			except OSError as e:
				if "wkhtmltopdf" in str(e).lower() or "No wkhtmltopdf executable found" in str(e):
					frappe.throw(
						_("PDF generation failed: wkhtmltopdf is not installed or not configured properly. "
						  "Please contact your system administrator to install wkhtmltopdf. "
						  "For more information, visit: https://github.com/JazzCore/python-pdfkit/wiki/Installing-wkhtmltopdf"),
						title=_("PDF Generation Error")
					)
				else:
					# Re-raise if it's a different OSError
					raise
			except Exception as e:
				# Log other PDF generation errors but don't fail completely
				frappe.log_error(
					_("Error generating PDF for salary slip {0}: {1}").format(self.name, str(e)),
					"Salary Slip PDF Generation Error"
				)
				frappe.throw(
					_("Error generating PDF attachment: {0}. Email will be sent without attachment.").format(str(e)),
					title=_("PDF Generation Warning")
				)

			email_args = {
				"sender": payroll_settings.sender_email,
				"recipients": [receiver],
				"message": message,
				"subject": subject,
				"attachments": attachments,
				"reference_doctype": self.doctype,
				"reference_name": self.name,
			}
			if not frappe.flags.in_test:
				enqueue(method=frappe.sendmail, queue="short", timeout=300, is_async=True, **email_args)
			else:
				frappe.sendmail(**email_args)
		else:
			msgprint(_("{0}: Employee email not found, hence email not sent").format(self.employee_name))

	def update_status(self, salary_slip=None):
		for data in self.timesheets:
			if data.time_sheet:
				timesheet = frappe.get_doc("Timesheet", data.time_sheet)
				timesheet.salary_slip = salary_slip
				timesheet.flags.ignore_validate_update_after_submit = True
				timesheet.set_status()
				timesheet.save()

	def set_status(self, status=None):
		"""Get and update status"""
		if not status:
			status = self.get_status()
		self.db_set("status", status)

	def process_salary_structure(self, for_preview=0):
		"""Calculate salary after salary structure details have been updated"""
		if not self.salary_slip_based_on_timesheet:
			self.get_date_details()
		self.pull_emp_details()
		self.get_working_days_details(for_preview=for_preview)
		self.calculate_net_pay()

	def pull_emp_details(self):
		account_details = frappe.get_cached_value(
			"Employee", self.employee, ["bank_name", "bank_ac_no", "salary_mode"], as_dict=1
		)
		if account_details:
			self.bank_name = account_details.bank_name
			self.bank_account_no = account_details.bank_ac_no
			# Prefer a Mode of Payment matching Employee.salary_mode when it exists
			if account_details.salary_mode and frappe.db.exists("Mode of Payment", account_details.salary_mode):
				self.mode_of_payment = account_details.salary_mode

	@frappe.whitelist()
	def process_salary_based_on_working_days(self):
		self.get_working_days_details(lwp=self.leave_without_pay)
		self.calculate_net_pay()

	@frappe.whitelist()
	def set_totals(self):
		self.gross_pay = 0.0
		if self.salary_slip_based_on_timesheet == 1:
			self.calculate_total_for_salary_slip_based_on_timesheet()
		else:
			self.total_deduction = 0.0
			if hasattr(self, "earnings"):
				for earning in self.earnings:
					self.gross_pay += flt(earning.amount, earning.precision("amount"))
			if hasattr(self, "deductions"):
				for deduction in self.deductions:
					self.total_deduction += flt(deduction.amount, deduction.precision("amount"))
			self.net_pay = (
				flt(self.gross_pay) - flt(self.total_deduction) - flt(self.get("total_loan_repayment"))
			)
		self.set_base_totals()

	def set_base_totals(self):
		self.base_gross_pay = flt(self.gross_pay) * flt(self.exchange_rate)
		self.base_total_deduction = flt(self.total_deduction) * flt(self.exchange_rate)
		self.rounded_total = rounded(self.net_pay or 0)
		self.base_net_pay = flt(self.net_pay) * flt(self.exchange_rate)
		self.base_rounded_total = rounded(self.base_net_pay or 0)
		self.set_net_total_in_words()

	# calculate total working hours, earnings based on hourly wages and totals
	def calculate_total_for_salary_slip_based_on_timesheet(self):
		if self.timesheets:
			self.total_working_hours = 0
			for timesheet in self.timesheets:
				if timesheet.working_hours:
					self.total_working_hours += timesheet.working_hours

		wages_amount = self.total_working_hours * self.hour_rate
		self.base_hour_rate = flt(self.hour_rate) * flt(self.exchange_rate)
		salary_component = frappe.db.get_value(
			"Salary Structure", {"name": self.salary_structure}, "salary_component", cache=True
		)
		if self.earnings:
			for i, earning in enumerate(self.earnings):
				if earning.salary_component == salary_component:
					self.earnings[i].amount = wages_amount
				self.gross_pay += flt(self.earnings[i].amount, earning.precision("amount"))
		self.net_pay = flt(self.gross_pay) - flt(self.total_deduction)

	def compute_year_to_date(self):
		year_to_date = 0
		period_start_date, period_end_date = self.get_year_to_date_period()

		salary_slip_sum = frappe.get_list(
			"Salary Slip",
			fields=["sum(net_pay) as net_sum", "sum(gross_pay) as gross_sum"],
			filters={
				"employee": self.employee,
				"start_date": [">=", period_start_date],
				"end_date": ["<", period_end_date],
				"name": ["!=", self.name],
				"docstatus": 1,
			},
		)

		year_to_date = flt(salary_slip_sum[0].net_sum) if salary_slip_sum else 0.0
		gross_year_to_date = flt(salary_slip_sum[0].gross_sum) if salary_slip_sum else 0.0

		year_to_date += self.net_pay
		gross_year_to_date += self.gross_pay
		self.year_to_date = year_to_date
		self.gross_year_to_date = gross_year_to_date

	def aggregate_emolument(self, emoluments_data, emolument_type):
		total = 0
		for component, amount in emoluments_data["total_earnings"].items():
			mapped_type = SALARY_COMPONENT_TO_EMOLUMENT_TYPE.get(component)
			if mapped_type == emolument_type:
				total += amount
		
		for component, amount in emoluments_data["total_deductions"].items():
			mapped_type = SALARY_COMPONENT_TO_EMOLUMENT_TYPE.get(component)
		
			if mapped_type == emolument_type:
				total += amount

		return total

	def compute_period_emoluments(self, period_start_date=None, period_end_date=None):
		if not period_end_date:
			period_end_date = getdate(self.end_date)
		else:
			period_end_date = getdate(period_end_date)

		# 1st July of previous year
		period_start_date = date(period_end_date.year - 1, 7, 1)
		# 30th June of current year
		period_end_date = date(period_end_date.year, 6, 30)
		
		# Get all salary slips for the period
		salary_slips = frappe.get_list(
			"Salary Slip",
			fields=["name", "start_date", "end_date", "gross_pay", "total_deduction", "net_pay"],
			filters={
				"employee": self.employee,
				"start_date": [">=", period_start_date],
				"end_date": ["<=", period_end_date],
				"docstatus": 1,
			},
			order_by="start_date"
		)
		# Get detailed earnings and deductions breakdown
		emoluments_data = {
			"salary_slips": [],
			"exempt_income": {},  # Initialize exempt income for Transport Allowance
			"total_earnings": {},
			"total_deductions": {},
			"period_totals": {
				"gross_pay": 0,
				"total_deduction": 0,
				"net_pay": 0
			}
		}

		exempt_transport_total = 0
		
		for slip in salary_slips:
			slip_doc = frappe.get_doc("Salary Slip", slip.name)

			basic_salary = None
			car_allowance = None
			mileage = None
			busfare = None

			for earning in slip_doc.earnings:
				if earning.salary_component == "Basic":
					basic_salary = earning.amount
					break
			
			for earning in slip_doc.earnings:
				if earning.salary_component == "Car Allowance":
					car_allowance = earning.amount
					break
			
			earnings, deductions = get_salary_components_via_db(slip_doc.name)

			mileage = earnings.get("Mileage Allowance", 0)
			busfare = earnings.get("Busfare", 0)

			exempt_transport_allowance = calculate_exempt_transport_allowance(basic_salary, car_allowance) if basic_salary and car_allowance else 0
			exempt_transport_total += exempt_transport_allowance + mileage + busfare

			# Aggregate earnings by component
			for earning in slip_doc.earnings:
				component = earning.salary_component

				if component not in emoluments_data["total_earnings"]:
					emoluments_data["total_earnings"][component] = 0
				emoluments_data["total_earnings"][component] += earning.amount
			
			# Aggregate deductions by component
			for deduction in slip_doc.deductions:
				component = deduction.salary_component
				mapped_type = SALARY_COMPONENT_TO_EMOLUMENT_TYPE.get(component)
				
				if mapped_type == "salary_wages_basic":
					if "Other Taxable Deductions" not in emoluments_data["total_earnings"]:
						emoluments_data["total_earnings"]["Other Taxable Deductions"] = 0
					emoluments_data["total_earnings"]["Other Taxable Deductions"] -= deduction.amount
				else:
					if component not in emoluments_data["total_deductions"]:
						emoluments_data["total_deductions"][component] = 0
					emoluments_data["total_deductions"][component] += deduction.amount

			# Add to period totals
			emoluments_data["period_totals"]["gross_pay"] += slip.gross_pay
			emoluments_data["period_totals"]["total_deduction"] += slip.total_deduction
			emoluments_data["period_totals"]["net_pay"] += slip.net_pay
			emoluments_data["exempt_transport_total"] = exempt_transport_total
			emoluments_data["salary_slips"].append(slip)
		
		return emoluments_data

	def compute_period_emoluments_eoy(self, period_start_date=None, period_end_date=None):
		if period_start_date:
			period_start = getdate(period_start_date)
		else:
			period_start = getdate(self.start_date)

		if period_end_date:
			period_end = getdate(period_end_date)
		else:
			period_end = getdate(self.end_date)

		# validate
		if not period_start or not period_end or period_start > period_end:
			return {
				"salary_slips": [],
				"exempt_income": {},
				"total_earnings": {},
				"total_deductions": {},
				"period_totals": {"gross_pay": 0, "total_deduction": 0, "net_pay": 0},
			}

		# Get all submitted salary slips for the employee within the exact date range
		salary_slips = frappe.get_list(
			"Salary Slip",
			fields=["name", "start_date", "end_date", "gross_pay", "total_deduction", "net_pay"],
			filters={
				"employee": self.employee,
				"start_date": [">=", period_start],
				"end_date": ["<=", period_end],
				"docstatus": 1,
			},
			order_by="start_date",
		)

		emoluments_data = {
			"salary_slips": [],
			"exempt_income": {},
			"total_earnings": {},
			"total_deductions": {},
			"period_totals": {"gross_pay": 0, "total_deduction": 0, "net_pay": 0},
		}

		exempt_transport_total = 0

		for slip in salary_slips:
			slip_doc = frappe.get_doc("Salary Slip", slip.name)

			# collect basic and car allowance for transport exemption calculation
			basic_salary = 0
			car_allowance = 0

			for earning in slip_doc.earnings:
				if earning.salary_component == "Basic":
					basic_salary = earning.amount or 0
				if earning.salary_component == "Car Allowance":
					car_allowance = earning.amount or 0

			earnings, deductions = get_salary_components_via_db(slip_doc.name)

			mileage = earnings.get("Mileage Allowance", 0)
			busfare = earnings.get("Busfare", 0)

			exempt_transport_allowance = (
				calculate_exempt_transport_allowance(basic_salary, car_allowance)
				if basic_salary and car_allowance
				else 0
			)
			exempt_transport_total += exempt_transport_allowance + (mileage or 0) + (busfare or 0)

			# Aggregate earnings by component
			for earning in slip_doc.earnings:
				component = earning.salary_component
				emoluments_data["total_earnings"].setdefault(component, 0)
				emoluments_data["total_earnings"][component] += earning.amount or 0

			# Aggregate deductions by component
			for deduction in slip_doc.deductions:
				component = deduction.salary_component
				mapped_type = SALARY_COMPONENT_TO_EMOLUMENT_TYPE.get(component)
				# keep same behaviour as original: treat some deductions as negative earnings if mapped
				if mapped_type == "salary_wages_basic":
					emoluments_data["total_earnings"].setdefault("Other Taxable Deductions", 0)
					emoluments_data["total_earnings"]["Other Taxable Deductions"] -= deduction.amount or 0
				else:
					emoluments_data["total_deductions"].setdefault(component, 0)
					emoluments_data["total_deductions"][component] += deduction.amount or 0

			# Add to period totals
			emoluments_data["period_totals"]["gross_pay"] += slip.gross_pay or 0
			emoluments_data["period_totals"]["total_deduction"] += slip.total_deduction or 0
			emoluments_data["period_totals"]["net_pay"] += slip.net_pay or 0
			emoluments_data["exempt_transport_total"] = exempt_transport_total
			emoluments_data["salary_slips"].append(slip)

		return emoluments_data
	
	@frappe.whitelist()
	def get_dependent_deduction(self, employee, fiscal_year):
		"""
		Returns the dependent deduction amount for the given employee and fiscal year.
		"""
		# Get the employee's number of dependents (edf)
		edf = frappe.db.get_value("Employee", employee, "edf") or 0
		edf = int(edf)
		year_map = deduction_map.get(fiscal_year, {})
		return year_map.get(edf, 0)
	
	@frappe.whitelist()
	def get_fiscal_year_end(self, slip_end_date):
		# slip_end_date: a datetime.date or string (convert to date if needed)
		slip_end_date = getdate(slip_end_date)
		if slip_end_date.month >= 7:
			# July to December: fiscal year ends next year
			fiscal_year_end = date(slip_end_date.year + 1, 6, 30)
		else:
			# January to June: fiscal year ends this year
			fiscal_year_end = date(slip_end_date.year, 6, 30)
		return fiscal_year_end

	@frappe.whitelist()
	def get_emoluments_statement_values(self, period_start_date=None, period_end_date=None, declaration_date=None, signatory=None):
		"""Compute Statement of Emoluments field values for Mauritius FY (1 Jul – 30 Jun)."""
		if period_end_date:
			period_end_date = self.get_fiscal_year_end(period_end_date)
		else:
			period_end_date = self.get_fiscal_year_end(self.end_date)

		if period_start_date:
			period_start_date = getdate(period_start_date)
		else:
			period_start_date = date(getdate(period_end_date).year - 1, 7, 1)

		employee = frappe.get_doc("Employee", self.employee)
		company = frappe.get_doc("Company", self.company)
		emoluments_data = self.compute_period_emoluments(period_start_date, period_end_date)
		salary_wages_basic = self.aggregate_emolument(emoluments_data, "salary_wages_basic")
		transport_allowance = self.aggregate_emolument(emoluments_data, "transport_allowance")
		contributions_to_prgf = self.aggregate_emolument(emoluments_data, "contributions_to_prgf")
		tax_withheld_and_remitted = self.aggregate_emolument(emoluments_data, "tax_withheld_and_remitted")
		unpaid_leaves = self.aggregate_emolument(emoluments_data, "unpaid_leave")
		reimbursement_travelling_expenses = self.aggregate_emolument(emoluments_data, "reimbursement_travelling_expenses")
		other_allowance = self.aggregate_emolument(emoluments_data, "other_allowance")
		reimbursement_personal_expenses = self.aggregate_emolument(emoluments_data, "reimbursement_personal_expenses")
		reimbursement_passages = self.aggregate_emolument(emoluments_data, "reimbursement_passages")
		fringe_benefits = self.aggregate_emolument(emoluments_data, "fringe_benefits")
		lump_sum_commutation = self.aggregate_emolument(emoluments_data, "lump_sum_commutation")
		retirement_pension = self.aggregate_emolument(emoluments_data, "retirement_pension")
		bonus_year_date = date(getdate(period_end_date).year - 1, 12, 31)
		income_year = getdate(period_end_date).year

		bonus_including_end_of_year = flt(
			frappe.db.get_value(
				"EOY Bonus",
				{"nid": employee.nid, "bonus_year": bonus_year_date},
				"eoy_bonus",
			)
		)

		salary_wages_basic_net = flt(salary_wages_basic) - flt(unpaid_leaves)
		travelling = flt(transport_allowance) + flt(reimbursement_travelling_expenses)
		exempt_income = flt(emoluments_data.get("exempt_transport_total"))

		total_emoluments = (
			flt(salary_wages_basic_net)
			+ flt(bonus_including_end_of_year)
			+ flt(transport_allowance)
			+ flt(reimbursement_travelling_expenses)
			+ flt(other_allowance)
			+ flt(reimbursement_personal_expenses)
			+ flt(reimbursement_passages)
			+ flt(fringe_benefits)
			+ flt(lump_sum_commutation)
			+ flt(retirement_pension)
		)

		return {
			"employee": self.employee,
			"employer_full_name": company.registered_name,
			"paye_employer_registration_number": company.domain,
			"business_registration_number": company.brn,
			"tax_account_no": employee.tan,
			"employee_full_name": employee.employee_name,
			"national_identity_card_no": employee.nid,
			"income_year": income_year,
			"employed_from": employee.date_of_joining,
			"employed_to": employee.relieving_date or period_end_date,
			"salary_wages_basic": salary_wages_basic_net,
			"exempt_income": exempt_income,
			"tax_withheld_and_remitted": flt(tax_withheld_and_remitted),
			"transport_allowance": 0,
			"reimbursement_travelling_expenses": travelling,
			"other_allowance": flt(other_allowance),
			"reimbursement_personal_expenses": flt(reimbursement_personal_expenses),
			"reimbursement_passages": flt(reimbursement_passages),
			"fringe_benefits": flt(fringe_benefits),
			"lump_sum_commutation": flt(lump_sum_commutation),
			"retirement_pension": flt(retirement_pension),
			"bonus_including_end_of_year": bonus_including_end_of_year,
			"relief_deductions_allowances": self.get_dependent_deduction(
				self.employee, fiscal_year=income_year
			),
			"contributions_to_prgf": flt(contributions_to_prgf),
			"declaration_date": declaration_date or getdate(),
			"signatory": signatory,
			"total_emoluments": total_emoluments,
			"emoluments_net_of_exempt_income": total_emoluments - exempt_income,
			"period_start_date": period_start_date,
			"period_end_date": period_end_date,
		}

	@frappe.whitelist()
	def generate_emoluments_statement(self, period_start_date=None, period_end_date=None, declaration_date=None, signatory=None):
		"""Generate a comprehensive statement of emoluments"""
		values = self.get_emoluments_statement_values(
			period_start_date=period_start_date,
			period_end_date=period_end_date,
			declaration_date=declaration_date,
			signatory=signatory,
		)
		income_year = values["income_year"]

		existing_statement = frappe.db.get_value(
			"Statement of Emoluments",
			{"employee": self.employee, "income_year": income_year},
			"name",
		)

		if existing_statement:
			link = frappe.utils.get_link_to_form("Statement of Emoluments", existing_statement)
			frappe.throw(
				_("A Statement of Emoluments for this employee and year already exists: {0}").format(link),
				title=_("Duplicate Statement"),
			)

		statement = frappe.new_doc("Statement of Emoluments")
		for field, value in values.items():
			if field in ("period_start_date", "period_end_date"):
				continue
			if statement.meta.has_field(field):
				statement.set(field, value)

		statement.save(ignore_permissions=True)
		frappe.db.commit()

		return statement

	def compute_month_to_date(self):
		month_to_date = 0
		first_day_of_the_month = get_first_day(self.start_date)
		salary_slip_sum = frappe.get_list(
			"Salary Slip",
			fields=["sum(net_pay) as sum"],
			filters={
				"employee": self.employee,
				"start_date": [">=", first_day_of_the_month],
				"end_date": ["<", self.start_date],
				"name": ["!=", self.name],
				"docstatus": 1,
			},
		)

		month_to_date = flt(salary_slip_sum[0].sum) if salary_slip_sum else 0.0

		month_to_date += self.net_pay
		self.month_to_date = month_to_date

	def compute_component_wise_year_to_date(self):
		period_start_date, period_end_date = self.get_year_to_date_period()

		ss = frappe.qb.DocType("Salary Slip")
		sd = frappe.qb.DocType("Salary Detail")

		for key in ("earnings", "deductions"):
			for component in self.get(key):
				year_to_date = 0
				component_sum = (
					frappe.qb.from_(sd)
					.inner_join(ss)
					.on(sd.parent == ss.name)
					.select(Sum(sd.amount).as_("sum"))
					.where(
						(ss.employee == self.employee)
						& (sd.salary_component == component.salary_component)
						& (ss.start_date >= period_start_date)
						& (ss.end_date < period_end_date)
						& (ss.name != self.name)
						& (ss.docstatus == 1)
					)
				).run()

				year_to_date = flt(component_sum[0][0]) if component_sum else 0.0
				year_to_date += component.amount
				component.year_to_date = year_to_date

	def get_year_to_date_period(self):
		if self.payroll_period:
			period_start_date = self.payroll_period.start_date
			period_end_date = self.payroll_period.end_date
		else:
			# get dates based on fiscal year if no payroll period exists
			fiscal_year = get_fiscal_year(date=self.start_date, company=self.company, as_dict=1)
			period_start_date = fiscal_year.year_start_date
			period_end_date = fiscal_year.year_end_date

		return period_start_date, period_end_date

	def add_leave_balances(self):
		self.set("leave_details", [])

		if frappe.db.get_single_value("Payroll Settings", "show_leave_balances_in_salary_slip"):
			from hrms.hr.doctype.leave_application.leave_application import get_leave_details

			leave_details = get_leave_details(self.employee, self.end_date)

			for leave_type, leave_values in leave_details["leave_allocation"].items():
				self.append(
					"leave_details",
					{
						"leave_type": leave_type,
						"total_allocated_leaves": flt(leave_values.get("total_leaves")),
						"expired_leaves": flt(leave_values.get("expired_leaves")),
						"used_leaves": flt(leave_values.get("leaves_taken")),
						"pending_leaves": flt(leave_values.get("leaves_pending_approval")),
						"available_leaves": flt(leave_values.get("remaining_leaves")),
					},
				)

def unlink_ref_doc_from_salary_slip(doc, method=None):
	"""Unlinks accrual Journal Entry from Salary Slips on cancellation"""
	linked_ss = frappe.get_all(
		"Salary Slip", filters={"journal_entry": doc.name, "docstatus": ["<", 2]}, pluck="name"
	)

	if linked_ss:
		for ss in linked_ss:
			ss_doc = frappe.get_doc("Salary Slip", ss)
			frappe.db.set_value("Salary Slip", ss_doc.name, "journal_entry", "")


def generate_password_for_pdf(policy_template, employee):
	employee = frappe.get_cached_doc("Employee", employee)
	return policy_template.format(**employee.as_dict())


def get_salary_component_data(component):
	# get_cached_value doesn't work here due to alias "name as salary_component"
	return frappe.db.get_value(
		"Salary Component",
		component,
		(
			"name as salary_component",
			"depends_on_payment_days",
			"salary_component_abbr as abbr",
			"do_not_include_in_total",
			"is_tax_applicable",
			"is_flexible_benefit",
			"variable_based_on_taxable_salary",
		),
		as_dict=1,
		cache=True,
	)


def get_payroll_payable_account(company, payroll_entry):
	if payroll_entry:
		payroll_payable_account = frappe.db.get_value(
			"Payroll Entry", payroll_entry, "payroll_payable_account", cache=True
		)
	else:
		payroll_payable_account = frappe.db.get_value(
			"Company", company, "default_payroll_payable_account", cache=True
		)

	return payroll_payable_account


def calculate_tax_by_tax_slab(annual_taxable_earning, tax_slab, eval_globals=None, eval_locals=None):
	eval_locals.update({"annual_taxable_earning": annual_taxable_earning})
	tax_amount = 0
	for slab in tax_slab.slabs:
		cond = cstr(slab.condition).strip()
		if cond and not eval_tax_slab_condition(cond, eval_globals, eval_locals):
			continue
		if not slab.to_amount and annual_taxable_earning >= slab.from_amount:
			tax_amount += (annual_taxable_earning - slab.from_amount + 1) * slab.percent_deduction * 0.01
			continue

		if annual_taxable_earning >= slab.from_amount and annual_taxable_earning < slab.to_amount:
			tax_amount += (annual_taxable_earning - slab.from_amount + 1) * slab.percent_deduction * 0.01
		elif annual_taxable_earning >= slab.from_amount and annual_taxable_earning >= slab.to_amount:
			tax_amount += (slab.to_amount - slab.from_amount + 1) * slab.percent_deduction * 0.01

	# other taxes and charges on income tax
	for d in tax_slab.other_taxes_and_charges:
		if flt(d.min_taxable_income) and flt(d.min_taxable_income) > annual_taxable_earning:
			continue

		if flt(d.max_taxable_income) and flt(d.max_taxable_income) < annual_taxable_earning:
			continue

		tax_amount += tax_amount * flt(d.percent) / 100

	return tax_amount


def eval_tax_slab_condition(condition, eval_globals=None, eval_locals=None):
	if not eval_globals:
		eval_globals = {
			"int": int,
			"float": float,
			"long": int,
			"round": round,
			"date": date,
			"getdate": getdate,
		}

	try:
		condition = condition.strip()
		if condition:
			return frappe.safe_eval(condition, eval_globals, eval_locals)
	except NameError as err:
		frappe.throw(
			_("{0} <br> This error can be due to missing or deleted field.").format(err),
			title=_("Name error"),
		)
	except SyntaxError as err:
		frappe.throw(_("Syntax error in condition: {0} in Income Tax Slab").format(err))
	except Exception as e:
		frappe.throw(_("Error in formula or condition: {0} in Income Tax Slab").format(e))
		raise


def get_lwp_or_ppl_for_date_range(employee, start_date, end_date):
	LeaveApplication = frappe.qb.DocType("Leave Application")
	LeaveType = frappe.qb.DocType("Leave Type")

	leaves = (
		frappe.qb.from_(LeaveApplication)
		.inner_join(LeaveType)
		.on(LeaveType.name == LeaveApplication.leave_type)
		.select(
			LeaveApplication.name,
			LeaveType.is_ppl,
			LeaveType.fraction_of_daily_salary_per_leave,
			LeaveType.include_holiday,
			LeaveApplication.from_date,
			LeaveApplication.to_date,
			LeaveApplication.half_day,
			LeaveApplication.half_day_date,
		)
		.where(
			((LeaveType.is_lwp == 1) | (LeaveType.is_ppl == 1))
			& (LeaveApplication.docstatus == 1)
			& (LeaveApplication.status == "Approved")
			& (LeaveApplication.employee == employee)
			& ((LeaveApplication.salary_slip.isnull()) | (LeaveApplication.salary_slip == ""))
			& ((LeaveApplication.from_date >= start_date) & (LeaveApplication.to_date <= end_date))
		)
	).run(as_dict=True)

	leave_date_mapper = frappe._dict()
	for leave in leaves:
		if leave.from_date == leave.to_date:
			leave_date_mapper[leave.from_date] = leave
		else:
			date_diff = (getdate(leave.to_date) - getdate(leave.from_date)).days
			for i in range(date_diff + 1):
				date = add_days(leave.from_date, i)
				leave_date_mapper[date] = leave

	return leave_date_mapper


@frappe.whitelist()
def make_salary_slip_from_timesheet(source_name, target_doc=None):
	target = frappe.new_doc("Salary Slip")
	set_missing_values(source_name, target)
	target.run_method("get_emp_and_working_day_details")

	return target


def set_missing_values(time_sheet, target):
	doc = frappe.get_doc("Timesheet", time_sheet)
	target.employee = doc.employee
	target.employee_name = doc.employee_name
	target.salary_slip_based_on_timesheet = 1
	target.start_date = doc.start_date
	target.end_date = doc.end_date
	target.posting_date = doc.modified
	target.total_working_hours = doc.total_hours
	target.append("timesheets", {"time_sheet": doc.name, "working_hours": doc.total_hours})


def throw_error_message(row, error, title, description=None):
	data = frappe._dict(
		{
			"doctype": row.parenttype,
			"name": row.parent,
			"doclink": get_link_to_form(row.parenttype, row.parent),
			"row_id": row.idx,
			"error": error,
			"title": title,
			"description": description or "",
		}
	)

	message = _(
		"Error while evaluating the {doctype} {doclink} at row {row_id}. <br><br> <b>Error:</b> {error} <br><br> <b>Hint:</b> {description}"
	).format(**data)

	frappe.throw(message, title=title)


def on_doctype_update():
	frappe.db.add_index("Salary Slip", ["employee", "start_date", "end_date"])


def _safe_eval(code: str, eval_globals: dict | None = None, eval_locals: dict | None = None):
	"""Old version of safe_eval from framework.

	Note: current frappe.safe_eval transforms code so if you have nested
	iterations with too much depth then it can hit recursion limit of python.
	There's no workaround for this and people need large formulas in some
	countries so this is alternate implementation for that.

	WARNING: DO NOT use this function anywhere else outside of this file.
	"""
	code = unicodedata.normalize("NFKC", code)

	_check_attributes(code)

	whitelisted_globals = {"int": int, "float": float, "long": int, "round": round}
	if not eval_globals:
		eval_globals = {}

	eval_globals["__builtins__"] = {}
	eval_globals.update(whitelisted_globals)
	return eval(code, eval_globals, eval_locals)  # nosemgrep


def _check_attributes(code: str) -> None:
	import ast

	from frappe.utils.safe_exec import UNSAFE_ATTRIBUTES

	unsafe_attrs = set(UNSAFE_ATTRIBUTES).union(["__"]) - {"format"}

	for attribute in unsafe_attrs:
		if attribute in code:
			raise SyntaxError(f'Illegal rule {frappe.bold(code)}. Cannot use "{attribute}"')

	BLOCKED_NODES = (ast.NamedExpr,)

	tree = ast.parse(code, mode="eval")
	for node in ast.walk(tree):
		if isinstance(node, BLOCKED_NODES):
			raise SyntaxError(f"Operation not allowed: line {node.lineno} column {node.col_offset}")
		if isinstance(node, ast.Attribute) and isinstance(node.attr, str) and node.attr in UNSAFE_ATTRIBUTES:
			raise SyntaxError(f'Illegal rule {frappe.bold(code)}. Cannot use "{node.attr}"')
		
@frappe.whitelist()
def enqueue_email_salary_slips(names) -> None:
	"""enqueue bulk emailing salary slips"""
	import json

	if isinstance(names, str):
		names = json.loads(names)

	# Check Payroll Settings first (same as Payroll Entry)
	if not frappe.db.get_single_value("Payroll Settings", "email_salary_slip_to_employee"):
		frappe.throw(_("Email Salary Slip to Employee is not enabled in Payroll Settings"))

	if not names:
		frappe.throw(_("No salary slips selected"))

	# For small batches, execute directly (like Payroll Entry does for < 30)
	# For larger batches, enqueue
	if len(names) <= 30:
		try:
			email_salary_slips(names)
			frappe.msgprint(
				_("Salary slip emails have been sent. Check {0} for status.").format(
					f"""<a href='{frappe.utils.get_url_to_list("Email Queue")}' target='blank'>Email Queue</a>"""
				)
			)
		except Exception as e:
			frappe.log_error(
				_("Error sending salary slip emails: {0}").format(str(e)),
				"Salary Slip Email Error"
			)
			frappe.throw(_("Error sending emails. Please check Error Log for details."))
	else:
		# Enqueue for larger batches
		frappe.enqueue(
			"hrms.payroll.doctype.salary_slip.salary_slip.email_salary_slips",
			names=names,
			queue="short",
			timeout=300,
			is_async=True,
			enqueue_after_commit=True,
		)
		frappe.msgprint(
			_("Salary slip emails have been enqueued for sending. Check {0} for status.").format(
				f"""<a href='{frappe.utils.get_url_to_list("Email Queue")}' target='blank'>Email Queue</a>"""
			)
		)


def email_salary_slips(names) -> None:
	"""Send emails for multiple salary slips"""
	# Double-check Payroll Settings (in case called directly)
	if not frappe.db.get_single_value("Payroll Settings", "email_salary_slip_to_employee"):
		frappe.log_error(
			_("Email Salary Slip to Employee is not enabled in Payroll Settings"),
			"Salary Slip Email Error"
		)
		return

	success_count = 0
	failed_count = 0
	failed_slips = []

	for name in names:
		employee_name = "Unknown"
		try:
			salary_slip = frappe.get_doc("Salary Slip", name)
			employee_name = salary_slip.employee_name or salary_slip.employee or "Unknown"
			receiver = frappe.db.get_value("Employee", salary_slip.employee, "prefered_email", cache=True)
			
			if not receiver:
				failed_count += 1
				failed_slips.append({
					"name": name,
					"employee": employee_name,
					"reason": _("Employee email not found")
				})
				frappe.log_error(
					_("Email not sent for {0}: Employee {1} does not have prefered_email set").format(
						name, employee_name
					),
					"Salary Slip Email Error"
				)
			else:
				# Call email_salary_slip which handles the actual email sending
				salary_slip.email_salary_slip()
				success_count += 1
		except Exception as e:
			failed_count += 1
			failed_slips.append({
				"name": name,
				"employee": employee_name,
				"reason": str(e)
			})
			frappe.log_error(
				_("Error sending email for salary slip {0}: {1}").format(name, str(e)),
				"Salary Slip Email Error"
			)

	# Log summary
	if failed_count > 0 or success_count > 0:
		summary_msg = _("Salary slip email summary: {0} sent successfully, {1} failed").format(
			success_count, failed_count
		)
		if failed_slips:
			summary_msg += _(". Failed slips: {0}").format([f["name"] for f in failed_slips])
		frappe.log_error(summary_msg, "Salary Slip Email Summary")


@frappe.whitelist()
def get_salary_increase_for_period(employee, start_date, end_date):
	"""
	Module-level function to get salary increase details for a period.
	Can be called from Jinja templates via frappe.call().
	
	Args:
		employee: Employee ID
		start_date: Period start date
		end_date: Period end date
		
	Returns dict with:
		- has_increase: bool
		- change_amount: float
		- effective_date: date
		- change_type: str
		- days_before: int (days at old salary)
		- days_after: int (days at new salary)
	"""
	start_date = getdate(start_date)
	end_date = getdate(end_date)
	
	# Get salary history records effective within this period
	salary_history = frappe.db.sql("""
		SELECT 
			name,
			effective_from_date,
			change_amount,
			change_type,
			previous_basic_salary,
			new_basic_salary
		FROM `tabSalary History`
		WHERE employee = %(employee)s
			AND docstatus = 1
			AND effective_from_date >= %(start_date)s
			AND effective_from_date <= %(end_date)s
		ORDER BY effective_from_date DESC
		LIMIT 1
	""", {
		"employee": employee,
		"start_date": start_date,
		"end_date": end_date
	}, as_dict=True)
	
	if not salary_history:
		return {
			"has_increase": False,
			"change_amount": 0,
			"effective_date": None,
			"change_type": None,
			"days_before": 0,
			"days_after": 0
		}
	
	history = salary_history[0]
	effective_date = getdate(history.effective_from_date)
	
	# Calculate days before and after the increase
	days_before = date_diff(effective_date, start_date)
	days_after = date_diff(end_date, effective_date) + 1  # Include the effective date
	
	# Ensure days are not negative
	days_before = max(0, days_before)
	days_after = max(0, days_after)
	
	return {
		"has_increase": True,
		"change_amount": history.change_amount,
		"effective_date": history.effective_from_date,
		"change_type": history.change_type,
		"days_before": days_before,
		"days_after": days_after,
		"previous_basic_salary": history.previous_basic_salary,
		"new_basic_salary": history.new_basic_salary
	}