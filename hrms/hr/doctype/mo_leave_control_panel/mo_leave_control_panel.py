# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_link_to_form, getdate

from erpnext import get_default_company

from hrms.hr.utils import validate_bulk_tool_fields


class MOLeaveControlPanel(Document):
	def validate_fields(self, employees: list):
		mandatory_fields = ["from_date", "to_date"]
		validate_bulk_tool_fields(self, mandatory_fields, employees, "from_date", "to_date")

	@frappe.whitelist()
	def allocate_mo_leaves(self, employees: list):
		"""
		Create MO Leave Policy Assignments for selected employees.
		This method handles both new employees and yearly reassignment.
		When allocating for an employee with a previous assignment, bank leave transfers
		are automatically processed (unused leaves transferred to Bank Sick Leave and Bank Local Leave).
		"""
		self.validate_fields(employees)
		return self.create_mo_leave_policy_assignments(employees)

	def create_mo_leave_policy_assignments(self, employees: list) -> dict:
		"""
		Create and submit MO Leave Policy Assignments.
		For employees with previous assignments, bank leave transfers are automatically handled.
		effective_from is always beginning of year unless employee joining date is after beginning of year.
		"""
		failure = []
		success = []
		savepoint = "before_mo_assignment_submission"

		# Ensure dates are beginning and end of year
		from frappe.utils import get_first_day, getdate
		from_date_obj = getdate(self.from_date)
		year_start = getdate(f"{from_date_obj.year}-01-01")
		year_end = getdate(f"{from_date_obj.year}-12-31")

		for employee in employees:
			try:
				frappe.db.savepoint(savepoint)
				assignment = frappe.new_doc("MO Leave Policy Assignment")
				assignment.employee = employee
				assignment.assignment_based_on = "Joining Date"
				
				# Get employee joining date
				date_of_joining = frappe.db.get_value("Employee", employee, "date_of_joining")
				
				# effective_from should be beginning of year unless employee joining date is after beginning of year
				if date_of_joining and getdate(date_of_joining) > year_start:
					assignment.effective_from = date_of_joining
				else:
					assignment.effective_from = year_start
				
				# effective_to is always end of year
				assignment.effective_to = year_end
				
				assignment.save()
				assignment.submit()
				success.append(
					{
						"doc": get_link_to_form("MO Leave Policy Assignment", assignment.name),
						"employee": employee,
					}
				)
			except Exception as e:
				frappe.db.rollback(save_point=savepoint)
				error_message = str(e)
				# Clean up error message - remove "Reference:" patterns
				import re
				error_message = re.sub(r'\s*Reference:\s*[A-Z0-9-]+\s*', '', error_message)
				# Extract just the error message if it's a ValidationError
				if hasattr(e, 'message'):
					error_message = str(e.message) if e.message else error_message
				frappe.log_error(
					f"MO Leave Policy Assignment failed for employee {employee}: {error_message}",
					"MO Leave Control Panel Error"
				)
				failure.append({"employee": employee, "error": error_message})

		frappe.clear_messages()
		frappe.publish_realtime(
			"completed_bulk_mo_leave_policy_assignment",
			message={"success": success, "failure": failure},
			doctype="MO Leave Control Panel",
			after_commit=True,
		)

		return {"success": success, "failure": failure}


	@frappe.whitelist()
	def get_employees(self, advanced_filters: list) -> list:
		"""Get employees without MO assignments in the period"""
		if not (self.from_date and self.to_date):
			return []

		if all_employees := frappe.get_list(
			"Employee",
			filters=self.get_filters() + advanced_filters,
			fields=["name", "employee", "employee_name", "company", "department", "date_of_joining"],
		):
			# Filter by tenure if specified
			filtered_employees = self.filter_by_tenure(all_employees)
			return self.get_employees_without_mo_assignments(filtered_employees, self.from_date, self.to_date)

		return []

	def filter_by_tenure(self, employees: list) -> list:
		"""Filter employees by tenure based on tenure_filter selection"""
		if not self.tenure_filter or not self.from_date:
			return employees

		from frappe.utils import getdate
		from hrms.hr.doctype.mo_leave_policy_assignment.mo_leave_policy_assignment import (
			MOLeavePolicyAssignment,
		)

		filtered = []
		effective_from = getdate(self.from_date)

		for emp in employees:
			if not emp.date_of_joining:
				continue

			# Calculate tenure in months using static method
			tenure_months = MOLeavePolicyAssignment.calculate_tenure_months_static(
				emp.date_of_joining, effective_from
			)

			# Apply filter
			if self.tenure_filter == "< 6 months" and tenure_months < 6:
				filtered.append(emp)
			elif self.tenure_filter == "6-12 months" and 6 <= tenure_months < 12:
				filtered.append(emp)
			elif self.tenure_filter == "12+ months" and tenure_months >= 12:
				filtered.append(emp)

		return filtered

	def get_employees_without_mo_assignments(
		self, all_employees: list, from_date: str, to_date: str
	) -> list:
		"""Filter employees who don't have MO assignments in the period"""
		MOAssignment = frappe.qb.DocType("MO Leave Policy Assignment")

		query = (
			frappe.qb.from_(MOAssignment)
			.select(MOAssignment.employee)
			.distinct()
			.where(
				(MOAssignment.docstatus == 1)
				& (MOAssignment.employee.isin([d.name for d in all_employees]))
			)
		)

		# Check for overlapping date ranges
		# Assignment overlaps if:
		# - Assignment from_date is between filter from_date and to_date, OR
		# - Assignment to_date is between filter from_date and to_date, OR
		# - Assignment completely contains the filter period
		query = query.where(
			(
				(MOAssignment.effective_from >= from_date)
				& (MOAssignment.effective_from <= to_date)
			)
			| (
				(MOAssignment.effective_to >= from_date)
				& (MOAssignment.effective_to <= to_date)
			)
			| (
				(MOAssignment.effective_from <= from_date)
				& (MOAssignment.effective_to >= to_date)
			)
		)

		employees_with_assignments = query.run(pluck=True)
		return [d for d in all_employees if d.name not in employees_with_assignments]

	def get_filters(self):
		"""Get employee filters based on control panel settings"""
		filter_fields = [
			"company",
			"employment_type",
			"branch",
			"department",
			"designation",
			"employee_grade",
		]
		filters = [["status", "=", "Active"]]

		for d in filter_fields:
			if self.get(d):
				if d == "employee_grade":
					filters.append(["grade", "=", self.get(d)])
				else:
					filters.append([d, "=", self.get(d)])
		return filters

	@frappe.whitelist()
	def run_daily_scheduler_manual(self):
		"""
		Manually trigger the daily scheduler for testing purposes.
		This runs the same logic as the scheduled daily job.
		"""
		from hrms.hr.utils import allocate_mo_threshold_leaves
		from frappe.utils import getdate
		
		result = allocate_mo_threshold_leaves(target_date=getdate())
		
		# Format result for display
		success_count = len(result.get("success", []))
		failure_count = len(result.get("failure", []))
		skipped = result.get("skipped")
		
		if skipped:
			frappe.msgprint(
				_("Daily scheduler skipped: {0}").format(skipped),
				indicator="blue",
				title=_("Scheduler Status"),
			)
		elif success_count > 0 or failure_count > 0:
			message = _("Daily scheduler completed: {0} successful, {1} failed").format(
				success_count, failure_count
			)
			if failure_count > 0:
				frappe.msgprint(
					message,
					indicator="orange",
					title=_("Scheduler Results"),
				)
				# Log failures
				for failure in result.get("failure", []):
					frappe.log_error(
						f"Daily scheduler failed for {failure.get('employee', 'unknown')}: {failure.get('error', 'unknown error')}",
						"MO Daily Scheduler Manual Trigger"
					)
			else:
				frappe.msgprint(
					message,
					indicator="green",
					title=_("Scheduler Results"),
				)
		else:
			frappe.msgprint(
				_("Daily scheduler completed: No employees processed"),
				indicator="blue",
				title=_("Scheduler Results"),
			)
		
		return result
