# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""
Test script for Mauritius Leave Management System

This script provides helper functions to test the leave management system.
Run individual test cases or all tests.

Usage:
    bench execute hrms.hr.doctype.leave_refund.test_leave_management.run_all_tests
    bench execute hrms.hr.doctype.leave_refund.test_leave_management.test_lwp_sunday_exclusion
"""

import frappe
from frappe.utils import add_days, getdate, today, get_first_day
from datetime import datetime
import erpnext
import erpnext


def cleanup_allocation(allocation_name):
	"""Helper to clean up leave allocation and related ledger entries"""
	if not allocation_name or not frappe.db.exists("Leave Allocation", allocation_name):
		return
	
	try:
		allocation = frappe.get_doc("Leave Allocation", allocation_name)
		
		# Delete Leave Ledger Entries first (using direct SQL to bypass validations)
		frappe.db.sql("""
			DELETE FROM `tabLeave Ledger Entry`
			WHERE transaction_name = %s
		""", allocation_name)
		
		# Update leave policy assignment if linked
		if allocation.leave_policy_assignment:
			frappe.db.sql("""
				UPDATE `tabLeave Policy Assignment`
				SET leaves_allocated = 0
				WHERE name = %s
			""", allocation.leave_policy_assignment)
		
		# Cancel allocation if submitted
		if allocation.docstatus == 1:
			try:
				# Use direct SQL to update docstatus to avoid validation
				frappe.db.sql("""
					UPDATE `tabLeave Allocation`
					SET docstatus = 2
					WHERE name = %s
				""", allocation_name)
			except:
				# If that fails, try normal cancel
				try:
					allocation.reload()
					allocation.cancel()
				except:
					pass
		
		# Force delete using direct SQL
		frappe.db.sql("""
			DELETE FROM `tabLeave Allocation`
			WHERE name = %s
		""", allocation_name)
		
	except Exception as e:
		# Final fallback - direct SQL delete
		try:
			frappe.db.sql("""
				DELETE FROM `tabLeave Ledger Entry`
				WHERE transaction_name = %s
			""", allocation_name)
			frappe.db.sql("""
				DELETE FROM `tabLeave Allocation`
				WHERE name = %s
			""", allocation_name)
		except:
			pass


def create_salary_structure_for_employee(employee, company=None, currency=None):
	"""Create a minimal salary structure and assignment for testing"""
	if not company:
		company = frappe.get_value("Employee", employee, "company")
	if not currency:
		currency = frappe.get_value("Company", company, "default_currency")
	
	# Check if salary structure already exists for this employee
	existing_assignment = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "docstatus": 1},
		"salary_structure"
	)
	if existing_assignment:
		return existing_assignment
	
	# Create a minimal salary structure
	salary_structure_name = f"Test Salary Structure - {employee}"
	
	if not frappe.db.exists("Salary Structure", salary_structure_name):
		salary_structure = frappe.new_doc("Salary Structure")
		salary_structure.name = salary_structure_name
		salary_structure.company = company
		salary_structure.currency = currency
		salary_structure.payroll_frequency = "Monthly"
		salary_structure.is_active = "Yes"
		
		# Get payment account
		payment_account = frappe.db.get_value(
			"Account",
			{"account_currency": currency, "account_type": "Payable", "is_group": 0},
			"name"
		)
		if not payment_account:
			# Try to get any payable account
			payment_account = frappe.db.get_value(
				"Account",
				{"account_type": "Payable", "is_group": 0, "company": company},
				"name"
			)
		if payment_account:
			salary_structure.payment_account = payment_account
		
		# Add a basic earning component
		# Check if Basic component exists, if not create it
		basic_component_name = frappe.db.get_value("Salary Component", {"salary_component": "Basic"}, "name")
		if not basic_component_name:
			# Create basic component if it doesn't exist
			basic_comp = frappe.new_doc("Salary Component")
			basic_comp.salary_component = "Basic"
			basic_comp.type = "Earning"
			basic_comp.insert(ignore_permissions=True)
			basic_component_name = basic_comp.name
		
		salary_structure.append("earnings", {
			"salary_component": basic_component_name,
			"amount": 50000
		})
		
		salary_structure.insert(ignore_permissions=True)
		salary_structure.submit()
	else:
		salary_structure = frappe.get_doc("Salary Structure", salary_structure_name)
	
	# Create salary structure assignment
	from_date = get_first_day(today())
	joining_date = frappe.get_value("Employee", employee, "date_of_joining")
	if joining_date and getdate(joining_date) > getdate(from_date):
		from_date = joining_date
	
	assignment = frappe.new_doc("Salary Structure Assignment")
	assignment.employee = employee
	assignment.salary_structure = salary_structure.name
	assignment.company = company
	assignment.currency = currency
	assignment.from_date = from_date
	assignment.base = 50000
	assignment.variable = 0
	
	# Get payroll payable account
	payroll_account = frappe.db.get_value("Company", company, "default_payroll_payable_account")
	if not payroll_account:
		# Try to get any payable account
		payroll_account = frappe.db.get_value(
			"Account",
			{"account_type": "Payable", "is_group": 0, "company": company},
			"name"
		)
	if payroll_account:
		assignment.payroll_payable_account = payroll_account
	
	assignment.insert(ignore_permissions=True)
	assignment.submit()
	
	return salary_structure.name


def cleanup_refund(refund_name):
	"""Helper to clean up leave refund and related documents"""
	if not refund_name or not frappe.db.exists("Leave Refund", refund_name):
		return
	
	try:
		refund = frappe.get_doc("Leave Refund", refund_name)
		
		# Cancel Additional Salary if exists
		if refund.additional_salary:
			try:
				additional_salary = frappe.get_doc("Additional Salary", refund.additional_salary)
				if additional_salary.docstatus == 1:
					additional_salary.cancel()
				frappe.delete_doc("Additional Salary", refund.additional_salary, force=1)
			except:
				pass
		
		# Delete Leave Ledger Entries
		frappe.db.sql("""
			DELETE FROM `tabLeave Ledger Entry`
			WHERE transaction_name = %s
		""", refund_name)
		
		# Cancel and delete refund
		if refund.docstatus == 1:
			refund.cancel()
		frappe.delete_doc("Leave Refund", refund_name, force=1)
	except Exception as e:
		# If cancel fails, try force delete
		try:
			frappe.delete_doc("Leave Refund", refund_name, force=1)
		except:
			pass


def create_test_employees():
	"""Create test employees with different joining dates"""
	employees = {}
	
	# Employee A: Joined < 6 months ago
	employees['A'] = create_employee(
		name="TEST-EMP-A",
		employee_name="Test Employee A",
		date_of_joining=add_days(today(), -150),  # ~5 months ago
		working_days=22
	)
	
	# Employee B: Joined 6-12 months ago
	employees['B'] = create_employee(
		name="TEST-EMP-B",
		employee_name="Test Employee B",
		date_of_joining=add_days(today(), -270),  # ~9 months ago
		working_days=22
	)
	
	# Employee C: Joined > 1 year ago
	employees['C'] = create_employee(
		name="TEST-EMP-C",
		employee_name="Test Employee C",
		date_of_joining=add_days(today(), -400),  # ~13 months ago
		working_days=22
	)
	
	# Employee D: 22 working days (5 days/week)
	employees['D'] = create_employee(
		name="TEST-EMP-D",
		employee_name="Test Employee D",
		date_of_joining=add_days(today(), -400),
		working_days=22
	)
	
	# Employee E: 26 working days (6 days/week)
	employees['E'] = create_employee(
		name="TEST-EMP-E",
		employee_name="Test Employee E",
		date_of_joining=add_days(today(), -400),
		working_days=26
	)
	
	return employees


def create_employee(name, employee_name, date_of_joining, working_days=26):
	"""Create a test employee"""
	# Check if employee exists by employee_name
	existing = frappe.db.get_value("Employee", {"employee_name": employee_name}, "name")
	if existing:
		return existing
	
	# Get or create Gender
	gender_name = frappe.db.get_value("Gender", {"gender": "Male"}, "name")
	if not gender_name:
		# Try to get any existing gender
		gender_name = frappe.db.get_value("Gender", {}, "name")
		if not gender_name:
			# Create Gender if it doesn't exist
			try:
				gender_doc = frappe.new_doc("Gender")
				gender_doc.gender = "Male"
				gender_doc.insert(ignore_permissions=True)
				gender_name = gender_doc.name
			except:
				# If Gender doctype doesn't exist, use direct SQL
				frappe.db.sql("""
					INSERT INTO `tabGender` (name, gender, creation, modified, modified_by, owner)
					VALUES (%s, %s, NOW(), NOW(), %s, %s)
				""", (frappe.generate_hash(length=10), "Male", frappe.session.user, frappe.session.user))
				gender_name = frappe.db.get_value("Gender", {"gender": "Male"}, "name")
	
	# Get company
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		company = frappe.db.get_value("Company", {"is_group": 0}, "name")
	if not company:
		company = frappe.db.get_value("Company", {}, "name")
	
	emp = frappe.new_doc("Employee")
	# Split employee_name for first_name and last_name
	name_parts = employee_name.split()
	emp.first_name = name_parts[0] if name_parts else "Test"
	emp.last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "Employee"
	emp.employee_name = employee_name
	emp.gender = gender_name
	emp.date_of_birth = add_days(date_of_joining, -7300)  # ~20 years before joining
	emp.date_of_joining = date_of_joining
	emp.working_days = str(working_days)
	emp.status = "Active"
	emp.company = company
	emp.insert(ignore_permissions=True)
	
	return emp.name


def test_lwp_sunday_exclusion():
	"""Test LWP Sunday exclusion for 22 working days employees"""
	print("\n" + "="*80)
	print("Test: LWP Sunday Exclusion (22 working days)")
	print("="*80)
	
	employee = create_employee("TEST-LWP-22", "Test LWP 22", add_days(today(), -400), working_days=22)
	
	# Create LWP application from Monday to next Monday (8 days, includes 1 Sunday)
	from_date = get_next_monday()
	to_date = add_days(from_date, 7)  # Next Monday
	
	from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days
	
	leave_days = get_number_of_leave_days(
		employee=employee,
		leave_type="Leave Without Pay",
		from_date=from_date,
		to_date=to_date
	)
	
	print(f"From: {from_date}, To: {to_date}")
	print(f"Calendar days: 8")
	print(f"Expected: 7 (excluding 1 Sunday)")
	print(f"Actual: {leave_days}")
	
	assert leave_days == 7, f"Expected 7 days, got {leave_days}"
	print("✅ PASS: Sunday excluded correctly")
	
	return True


def test_lwp_no_sunday_exclusion():
	"""Test LWP for 26 working days employees (Sunday not excluded)"""
	print("\n" + "="*80)
	print("Test: LWP No Sunday Exclusion (26 working days)")
	print("="*80)
	
	employee = create_employee("TEST-LWP-26", "Test LWP 26", add_days(today(), -400), working_days=26)
	
	from_date = get_next_monday()
	to_date = add_days(from_date, 7)
	
	from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days, get_holidays
	
	# Check how many holidays are in the period
	holidays_count = get_holidays(employee, from_date, to_date)
	
	leave_days = get_number_of_leave_days(
		employee=employee,
		leave_type="Leave Without Pay",
		from_date=from_date,
		to_date=to_date
	)
	
	expected_days = 8 - holidays_count  # Sunday is working day, only exclude holidays
	
	print(f"From: {from_date}, To: {to_date}")
	print(f"Calendar days: 8")
	print(f"Holidays in period: {holidays_count}")
	print(f"Expected: {expected_days} (excluding {holidays_count} holiday(s), Sunday is working day)")
	print(f"Actual: {leave_days}")
	
	# Should be 8 - holidays (Sunday included, only holidays excluded)
	assert leave_days == expected_days, f"Expected {expected_days} days, got {leave_days}"
	print("✅ PASS: Sunday not excluded (working day)")
	
	return True


def test_tenure_validation():
	"""Test tenure-based leave eligibility"""
	print("\n" + "="*80)
	print("Test: Tenure-Based Validation")
	print("="*80)
	
	employee_a = create_employee("TEST-TENURE-A", "Test Tenure A", add_days(today(), -150), working_days=22)
	
	# Clean up any existing allocations for this employee and leave type
	existing_allocations = frappe.get_all("Leave Allocation", 
		filters={"employee": employee_a, "leave_type": "Monthly Sick Leave"},
		fields=["name"])
	for alloc in existing_allocations:
		cleanup_allocation(alloc.name)
	
	# Create a leave allocation first to avoid "outside allocation period" error
	from hrms.hr.doctype.leave_application.leave_application import LeaveApplication
	from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days
	
	# First, test that we can't apply for Monthly Sick Leave
	# Create allocation to avoid allocation period error
	allocation = frappe.new_doc("Leave Allocation")
	allocation.employee = employee_a
	allocation.leave_type = "Monthly Sick Leave"
	allocation.from_date = add_days(today(), -365)
	allocation.to_date = add_days(today(), 365)
	allocation.new_leaves_allocated = 6
	allocation.insert(ignore_permissions=True)
	allocation.submit()
	
	app = frappe.new_doc("Leave Application")
	app.employee = employee_a
	app.leave_type = "Monthly Sick Leave"
	app.from_date = today()
	app.to_date = add_days(today(), 1)
	
	try:
		app.validate()
		app.insert()
		print("❌ FAIL: Should not allow Monthly Sick Leave for < 6 months employee")
		# Cleanup
		cleanup_allocation(allocation.name)
		return False
	except frappe.ValidationError as e:
		error_msg = str(e)
		# Check for various possible error message formats
		if any(phrase in error_msg.lower() for phrase in [
			"applicable after 180",
			"applicable only after",
			"6 months",
			"180 working days"
		]):
			print("✅ PASS: Tenure validation working correctly")
			print(f"   Error message: {error_msg}")
			# Cleanup
			cleanup_allocation(allocation.name)
			return True
		else:
			print(f"❌ FAIL: Wrong error message: {error_msg}")
			# Cleanup
			cleanup_allocation(allocation.name)
			return False


def test_leave_refund():
	"""Test leave refund functionality"""
	print("\n" + "="*80)
	print("Test: Leave Refund")
	print("="*80)
	
	employee = create_employee("TEST-REFUND", "Test Refund", add_days(today(), -400), working_days=22)
	
	# Create salary structure for the employee
	create_salary_structure_for_employee(employee)
	
	# Clean up any existing allocations for this employee and leave type
	existing_allocations = frappe.get_all("Leave Allocation", 
		filters={"employee": employee, "leave_type": "Local Leave"},
		fields=["name"])
	for alloc in existing_allocations:
		cleanup_allocation(alloc.name)
	
	# Create leave allocation first
	allocation = frappe.new_doc("Leave Allocation")
	allocation.employee = employee
	allocation.leave_type = "Local Leave"
	allocation.from_date = getdate()
	allocation.to_date = add_days(getdate(), 365)
	allocation.new_leaves_allocated = 11
	allocation.insert(ignore_permissions=True)
	allocation.submit()
	
	# Create leave refund
	refund = frappe.new_doc("Leave Refund")
	refund.employee = employee
	refund.leave_type = "Local Leave"
	refund.refund_days = 3
	refund.refund_date = today()
	refund.salary_component = "Leave Encashment"  # Or create custom component
	
	# Insert the refund document (salary structure is now available)
	refund.insert(ignore_permissions=True)
	
	# Get leave balance before
	balance_before = frappe.db.get_value("Leave Allocation", allocation.name, "total_leaves_allocated")
	
	try:
		refund.submit()
		
		# Get leave balance after
		balance_after = frappe.db.get_value("Leave Allocation", allocation.name, "total_leaves_allocated")
		
		print(f"Balance before: {balance_before}")
		print(f"Refund days: 3")
		print(f"Balance after: {balance_after}")
		
		assert balance_after == balance_before + 3, f"Balance should increase by 3, got {balance_after}"
		
		# Check Additional Salary created
		additional_salary = frappe.db.get_value("Leave Refund", refund.name, "additional_salary")
		assert additional_salary, "Additional Salary should be created"
		
		print("✅ PASS: Leave refund working correctly")
		
		# Cleanup
		cleanup_refund(refund.name)
		cleanup_allocation(allocation.name)
		
		return True
	except Exception as e:
		print(f"❌ FAIL: Leave refund test - {e}")
		# Cleanup on error
		try:
			if refund.name and frappe.db.exists("Leave Refund", refund.name):
				cleanup_refund(refund.name)
		except:
			pass
		try:
			if allocation.name:
				cleanup_allocation(allocation.name)
		except:
			pass
		return False


def test_local_leave_exists():
	"""Test that Local Leave exists and old types don't"""
	print("\n" + "="*80)
	print("Test: Local Leave Merge Verification")
	print("="*80)
	
	# Check Local Leave exists
	assert frappe.db.exists("Leave Type", "Local Leave"), "Local Leave should exist"
	print("✅ PASS: Local Leave exists")
	
	# Check old types don't exist
	assert not frappe.db.exists("Leave Type", "Local Leave Er"), "Local Leave Er should not exist"
	assert not frappe.db.exists("Leave Type", "Local Leave Ee"), "Local Leave Ee should not exist"
	print("✅ PASS: Old leave types removed")
	
	return True


def get_next_monday():
	"""Get next Monday date"""
	today_date = getdate()
	days_ahead = 0 - today_date.weekday()  # Monday is 0
	if days_ahead <= 0:
		days_ahead += 7
	return add_days(today_date, days_ahead)


def run_all_tests():
	"""Run all test cases"""
	print("\n" + "="*80)
	print("Mauritius Leave Management System - Test Suite")
	print("="*80)
	
	results = {}
	
	try:
		results['local_leave'] = test_local_leave_exists()
	except Exception as e:
		print(f"❌ FAIL: Local Leave test - {e}")
		results['local_leave'] = False
	
	try:
		results['lwp_22'] = test_lwp_sunday_exclusion()
	except Exception as e:
		print(f"❌ FAIL: LWP 22 test - {e}")
		results['lwp_22'] = False
	
	try:
		results['lwp_26'] = test_lwp_no_sunday_exclusion()
	except Exception as e:
		print(f"❌ FAIL: LWP 26 test - {e}")
		results['lwp_26'] = False
	
	try:
		results['tenure'] = test_tenure_validation()
	except Exception as e:
		print(f"❌ FAIL: Tenure validation test - {e}")
		results['tenure'] = False
	
	try:
		results['refund'] = test_leave_refund()
	except Exception as e:
		print(f"❌ FAIL: Leave refund test - {e}")
		results['refund'] = False
	
	# Summary
	print("\n" + "="*80)
	print("Test Summary")
	print("="*80)
	
	passed = sum(1 for v in results.values() if v)
	total = len(results)
	
	for test_name, result in results.items():
		status = "✅ PASS" if result else "❌ FAIL"
		print(f"{status}: {test_name}")
	
	print(f"\nTotal: {passed}/{total} tests passed")
	print("="*80 + "\n")
	
	return results

