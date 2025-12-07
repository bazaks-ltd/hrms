# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _, bold
from frappe.model.document import Document
from frappe.utils import flt, format_date, get_link_to_form, getdate

from hrms.hr.doctype.leave_application.leave_application import get_leaves_for_period
from hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry import create_leave_ledger_entry
from hrms.hr.utils import set_employee_name, validate_active_employee
from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
	get_assigned_salary_structure,
)


class LeaveRefund(Document):
	def validate(self):
		set_employee_name(self)
		validate_active_employee(self.employee)
		self.refund_date = self.refund_date or getdate()
		self.validate_refund_days()
		
		# Set currency if not set (get from company, not employee, to avoid salary structure requirement)
		if not self.currency:
			self.currency = frappe.get_value("Company", self.company, "default_currency")
		
		# Try to set salary structure and calculate refund amount
		# If refund_amount is already set, skip salary structure requirement
		# If not available, allow manual entry
		if not self.refund_amount or self.refund_amount == 0:
			if self.set_salary_structure():
				self.set_refund_amount()

	def set_salary_structure(self):
		try:
			self._salary_structure = get_assigned_salary_structure(self.employee, self.refund_date)
			if not self._salary_structure:
				# Don't throw error during validation - allow manual entry of refund amount
				# Error will be thrown in before_submit if refund_amount is not set
				return False
			return True
		except Exception:
			# If get_assigned_salary_structure throws an error (e.g., no salary structure),
			# allow manual entry of refund amount
			self._salary_structure = None
			return False

	def validate_refund_days(self):
		if self.refund_days <= 0:
			frappe.throw(_("Refund Days must be greater than 0"))

	def before_submit(self):
		if not self.refund_amount or self.refund_amount <= 0:
			# Try to calculate if not set
			if not hasattr(self, "_salary_structure") or not self._salary_structure:
				self.set_salary_structure()
			if hasattr(self, "_salary_structure") and self._salary_structure:
				self.set_refund_amount()
			
			# If still not set, throw error
			if not self.refund_amount or self.refund_amount <= 0:
				frappe.throw(_("You can only submit Leave Refund for a valid refund amount. Please set the refund amount manually or ensure employee has a salary structure assigned."))

	def on_submit(self):
		if not self.leave_allocation:
			self.db_set("leave_allocation", self.get_leave_allocation().get("name"))

		# Create Additional Salary entry
		additional_salary = frappe.new_doc("Additional Salary")
		additional_salary.company = frappe.get_value("Employee", self.employee, "company")
		additional_salary.employee = self.employee
		additional_salary.currency = self.currency
		additional_salary.salary_component = self.salary_component
		additional_salary.payroll_date = self.refund_date
		additional_salary.amount = self.refund_amount
		additional_salary.ref_doctype = self.doctype
		additional_salary.ref_docname = self.name
		additional_salary.submit()

		self.db_set("additional_salary", additional_salary.name)

		# Update Leave Allocation balance (add back refunded days)
		# Use direct SQL to avoid triggering validations
		if self.leave_allocation:
			current_total = frappe.db.get_value("Leave Allocation", self.leave_allocation, "total_leaves_allocated")
			new_total = flt(current_total) + flt(self.refund_days)
			frappe.db.sql("""
				UPDATE `tabLeave Allocation`
				SET total_leaves_allocated = %s
				WHERE name = %s
			""", (new_total, self.leave_allocation))

		# Create Leave Ledger Entry (positive entry to add days back)
		self.create_leave_ledger_entry()

	def on_cancel(self):
		if self.additional_salary:
			frappe.get_doc("Additional Salary", self.additional_salary).cancel()
			self.db_set("additional_salary", "")

		if self.leave_allocation:
			# Revert the allocation balance using direct SQL
			current_total = frappe.db.get_value("Leave Allocation", self.leave_allocation, "total_leaves_allocated")
			new_total = flt(current_total) - flt(self.refund_days)
			frappe.db.sql("""
				UPDATE `tabLeave Allocation`
				SET total_leaves_allocated = %s
				WHERE name = %s
			""", (new_total, self.leave_allocation))

		# Create reverse Leave Ledger Entry
		self.create_leave_ledger_entry(submit=False)

	@frappe.whitelist()
	def get_leave_details_for_refund(self):
		self.set_leave_balance()
		self.set_refund_amount()

	def set_leave_balance(self):
		allocation = self.get_leave_allocation()
		if not allocation:
			frappe.throw(
				_("No Leaves Allocated to Employee: {0} for Leave Type: {1}").format(
					self.employee, self.leave_type
				)
			)

		self.leave_balance = (
			allocation.total_leaves_allocated
			- allocation.carry_forwarded_leaves_count
			# adding this because the function returns a -ve number
			+ get_leaves_for_period(
				self.employee, self.leave_type, allocation.from_date, self.refund_date
			)
		)
		self.leave_allocation = allocation.name

	def set_refund_amount(self):
		if not hasattr(self, "_salary_structure") or not self._salary_structure:
			if not self.set_salary_structure():
				# No salary structure available - allow manual entry
				return

		if not self.salary_component:
			# Don't throw error, just return - amount can be set manually
			return

		try:
			# Try to get leave encashment amount per day from salary structure (if available)
			per_day_amount = frappe.db.get_value(
				"Salary Structure", self._salary_structure, "leave_encashment_amount_per_day"
			)
			
			if per_day_amount and per_day_amount > 0:
				self.refund_amount = self.refund_days * per_day_amount if self.refund_days else 0
			else:
				# Calculate from basic salary if encashment amount not set
				try:
					salary_structure = frappe.get_doc("Salary Structure", self._salary_structure)
					if salary_structure:
						# Calculate daily rate from basic salary
						basic_salary = 0
						for earning in salary_structure.get("earnings", []):
							if earning.salary_component == "Basic":
								basic_salary = earning.amount
								break

						if not basic_salary:
							# Fallback: use total earnings
							basic_salary = sum([e.amount for e in salary_structure.get("earnings", [])])

						# Get working days per month from employee
						working_days = frappe.db.get_value("Employee", self.employee, "working_days") or 26
						daily_rate = flt(basic_salary) / flt(working_days) if working_days else 0
						self.refund_amount = self.refund_days * daily_rate if self.refund_days else 0
					else:
						# If can't calculate, set to 0 and let user enter manually
						self.refund_amount = 0
				except Exception:
					# If can't get salary structure, set to 0 and let user enter manually
					self.refund_amount = 0
		except Exception:
			# If any error occurs (e.g., no salary structure), allow manual entry
			self.refund_amount = 0
		
		if not self.currency:
			self.currency = frappe.get_value("Company", self.company, "default_currency")

	def get_leave_allocation(self):
		date = self.refund_date or getdate()

		LeaveAllocation = frappe.qb.DocType("Leave Allocation")
		leave_allocation = (
			frappe.qb.from_(LeaveAllocation)
			.select(
				LeaveAllocation.name,
				LeaveAllocation.from_date,
				LeaveAllocation.to_date,
				LeaveAllocation.total_leaves_allocated,
				LeaveAllocation.carry_forwarded_leaves_count,
			)
			.where(
				((LeaveAllocation.from_date <= date) & (date <= LeaveAllocation.to_date))
				& (LeaveAllocation.docstatus == 1)
				& (LeaveAllocation.leave_type == self.leave_type)
				& (LeaveAllocation.employee == self.employee)
			)
		).run(as_dict=True)

		return leave_allocation[0] if leave_allocation else None

	def create_leave_ledger_entry(self, submit=True):
		# Positive entry to add days back to allocation
		args = frappe._dict(
			leaves=self.refund_days,
			from_date=self.refund_date,
			to_date=self.refund_date,
			is_carry_forward=0,
		)
		create_leave_ledger_entry(self, args, submit)

