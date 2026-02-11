# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _, bold
from frappe.model.document import Document
from frappe.utils import (
	add_months,
	cint,
	date_diff,
	flt,
	formatdate,
	get_link_to_form,
	getdate,
	rounded,
)
from datetime import timedelta

def _get_mo_rules():
	"""
	Read MO leave rules from the source-of-truth Single DocType.
	Falls back to defaults if the DocType is not created/migrated yet.
	"""
	defaults = {
		"first6_injury_leave_days": 14.0,
		"first6_training_leave_days": 10.0,
		"monthly_sick_leave_days": 6.0,
		"monthly_local_leave_days": 6.0,
		"year_plus_wedding_leave_days": 6.0,
		"year_plus_compassionate_leave_days": 3.0,
		"year_plus_sick_leave_days": 15.0,
		"year_plus_local_leave_days": 22.0,
		"year_plus_vacation_leave_days": 30.0,
		"year_plus_maternity_leave_days": 112.0,
		"year_plus_paternity_leave_days": 28.0,
		"vacation_eligible_after_years": 5,
	}

	if not frappe.db.table_exists("MO Leave Management System"):
		return frappe._dict(defaults)

	try:
		doc = frappe.get_single("MO Leave Management System")
		out = {**defaults}
		for k in out:
			if hasattr(doc, k) and doc.get(k) is not None:
				out[k] = doc.get(k)
		return frappe._dict(out)
	except Exception:
		return frappe._dict(defaults)


class MOLeavePolicyAssignment(Document):
	def validate(self):
		self.set_dates()
		self.validate_assignment_overlap()
		self.validate_employee_status()

	def on_submit(self):
		self.grant_leave_alloc_for_employee()

	def on_cancel(self):
		"""Cancel all leave allocations created by this MO assignment"""
		self.cancel_associated_leave_allocations()

	def cancel_associated_leave_allocations(self):
		"""
		Cancel all leave allocations that were created by this MO Leave Policy Assignment.
		Finds allocations by matching:
		1. Description field containing the assignment name (from on_submit)
		2. Description field containing "Assignment: {self.name}" (from daily scheduler)
		3. Description field containing "Bank leave allocation from MO Leave Policy Assignment {self.name}" (Bank leaves)
		"""
		# Find all leave allocations created by this assignment
		# Pattern 1: "Allocated via MO Leave Policy Assignment: {self.name}"
		# Pattern 2: "Auto-allocated via daily scheduler (..., Assignment: {self.name})"
		# Pattern 3: "Bank leave allocation from MO Leave Policy Assignment {self.name}"
		allocations = frappe.get_all(
			"Leave Allocation",
			filters={
				"employee": self.employee,
				"from_date": self.effective_from,
				"to_date": self.effective_to,
				"docstatus": 1,  # Only cancel submitted allocations
			},
			fields=["name", "leave_type", "description"],
		)

		# Filter allocations that match our assignment
		matching_allocations = []
		for alloc in allocations:
			desc = alloc.get("description", "") or ""
			# Match patterns:
			# 1. "Allocated via MO Leave Policy Assignment: {self.name}" (regular allocations)
			# 2. "Auto-allocated via daily scheduler (..., Assignment: {self.name})" (daily scheduler)
			# 3. "Bank leave allocation from MO Leave Policy Assignment {self.name}" (bank leaves)
			# 4. "Bank leave allocation from yearly reassignment" (if created via utility, check by leave type and period)
			if (
				f"MO Leave Policy Assignment: {self.name}" in desc
				or f"Assignment: {self.name}" in desc
				or f"Bank leave allocation from MO Leave Policy Assignment {self.name}" in desc
			):
				matching_allocations.append(alloc)
			# Also check for Bank Sick Leave allocations that might have been created via utility
			# but match our period (these are bank leaves created by this assignment)
			elif alloc.get("leave_type") in ["Bank Sick Leave"] and (
				"Bank leave allocation" in desc or desc == ""
			):
				# If it's a Bank Sick Leave in our period, it was likely created by this assignment
				# We'll include it to be safe (user can manually verify if needed)
				matching_allocations.append(alloc)

		if matching_allocations:
			cancelled = []
			failed = []

			for allocation in matching_allocations:
				try:
					alloc_doc = frappe.get_doc("Leave Allocation", allocation.name)
					alloc_doc.cancel()
					cancelled.append(allocation.name)
				except Exception as e:
					failed.append({"name": allocation.name, "leave_type": allocation.leave_type, "error": str(e)})
					frappe.log_error(
						f"Failed to cancel Leave Allocation {allocation.name} ({allocation.leave_type}) "
						f"for MO Leave Policy Assignment {self.name}: {str(e)}",
						"MO Leave Policy Assignment - Cancel Allocation Error"
					)

			if failed:
				frappe.msgprint(
					_("Some leave allocations could not be cancelled. Check Error Log for details."),
					indicator="orange",
					title=_("Partial Cancellation"),
				)
			elif cancelled:
				frappe.msgprint(
					_("Cancelled {0} leave allocation(s)").format(len(cancelled)),
					indicator="green",
					title=_("Allocations Cancelled"),
				)

	def set_dates(self):
		"""Set effective dates based on joining date"""
		if self.assignment_based_on == "Joining Date" and self.employee:
			date_of_joining = frappe.db.get_value("Employee", self.employee, "date_of_joining")
			if date_of_joining:
				# Only set effective_from if not already set (allows control panel to set it)
				if not self.effective_from:
					# Default to beginning of year unless joining date is after beginning of year
					from frappe.utils import getdate
					doj = getdate(date_of_joining)
					year_start = getdate(f"{doj.year}-01-01")
					if doj > year_start:
						self.effective_from = date_of_joining
					else:
						self.effective_from = year_start
				# effective_to should always be end of year
				if not self.effective_to:
					from frappe.utils import getdate
					from_date_obj = getdate(self.effective_from)
					self.effective_to = getdate(f"{from_date_obj.year}-12-31")

	def validate_assignment_overlap(self):
		"""Validate that there are no overlapping MO Leave Policy Assignments"""
		overlapping_assignment = frappe.db.get_value(
			"MO Leave Policy Assignment",
			{
				"employee": self.employee,
				"name": ("!=", self.name),
				"docstatus": 1,
				"effective_to": (">=", self.effective_from),
				"effective_from": ("<=", self.effective_to),
			},
			"name",
		)

		if overlapping_assignment:
			frappe.throw(
				_("MO Leave Policy Assignment already exists for Employee {0} for period {1} to {2}").format(
					bold(self.employee),
					bold(formatdate(self.effective_from)),
					bold(formatdate(self.effective_to)),
				),
				title=_("Assignment Overlap"),
			)

	def validate_employee_status(self):
		"""Validate that employee is active"""
		if self.employee:
			status = frappe.db.get_value("Employee", self.employee, "status")
			if status != "Active":
				frappe.throw(
					_("Cannot create MO Leave Policy Assignment for inactive employee {0}").format(
						bold(self.employee)
					),
					title=_("Invalid Employee Status"),
				)

	def grant_leave_alloc_for_employee(self):
		"""
		Grant leave allocations based on employee tenure.
		Automatically processes bank leave transfers from previous assignment if it exists.
		This handles yearly reassignment logic when HR manually allocates MO leaves each year.
		"""
		if self.leaves_allocated:
			frappe.throw(_("Leaves have already been allocated for this MO Leave Policy Assignment"))

		date_of_joining = frappe.db.get_value("Employee", self.employee, "date_of_joining")
		if not date_of_joining:
			frappe.throw(_("Employee {0} does not have a date of joining").format(bold(self.employee)))

		rules = _get_mo_rules()

		# Tenure at the assignment start date (effective_from)
		tenure_months = self.calculate_tenure_months(date_of_joining, self.effective_from)
		tenure_years = flt(tenure_months) / 12.0

		# Process bank leaves or carry forward monthly leaves based on tenure
		if tenure_months >= 12:
			# 12+ months: Process bank leaves from previous year
			# Also process Monthly Local Leave (carry forward) and Monthly Sick Leave (to Bank Sick Leave)
			self.process_bank_leaves_from_previous_assignment()
			self.carry_forward_monthly_leaves()  # Also process monthly leaves for 12+ employees
		elif 6 <= tenure_months < 12:
			# 6-12 months: Carry forward monthly leaves to new period
			self.carry_forward_monthly_leaves()

		leave_allocations = {}

		# First bucket leaves are allocated every year as part of yearly process (idempotent).
		# NOTE: LWP/Unpaid leaves are never allocated (framework blocks LWP allocations).
		first_bucket = {
			"Injury Leave": flt(rules.first6_injury_leave_days),
			"Training Leave (Paid)": flt(rules.first6_training_leave_days),
		}
		leave_allocations.update(self.allocate_leaves_for_period(first_bucket, date_of_joining))

		# 6–12 month leaves are NOT allocated here. HR (or the weekday-only daily allocator) handles them.

		# 12+ leaves are allocated if tenure >= 12 months at assignment start.
		if tenure_months >= 12:
			# Get unused balances from previous year for carry forward
			previous_year = getdate(self.effective_from).year - 1
			previous_period_start = getdate(f"{previous_year}-01-01")
			previous_period_end = getdate(f"{previous_year}-12-31")
			
			# Local Leave: Carry Forward + Prorated 22 days
			local_leave_carry_forward = self._get_unused_leave_balance_for_period(
				self.employee, "Local Leave", previous_period_start, previous_period_end
			)
			# Prorate the annual 22 days based on months from one-year anniversary
			prorated_local_leave = self.calculate_prorated_annual_leave(
				date_of_joining, flt(rules.year_plus_local_leave_days)
			)
			local_leave_total = local_leave_carry_forward + prorated_local_leave
			
			# Sick Leave: Prorated 15 days per year (previous unused moves to Bank Sick Leave, already handled in process_bank_leaves)
			prorated_sick_leave = self.calculate_prorated_annual_leave(
				date_of_joining, flt(rules.year_plus_sick_leave_days)
			)
			
			year_plus = {
				"Wedding Leave": flt(rules.year_plus_wedding_leave_days),  # Resets to 6
				"Compassionate Leave": flt(rules.year_plus_compassionate_leave_days),
				"Sick Leave": prorated_sick_leave,  # Prorated 15 days
				"Local Leave": local_leave_total,  # Carry Forward + Prorated 22 days
				"Maternity Leave": flt(rules.year_plus_maternity_leave_days),  # Resets to 112
				"Paternity Leave": flt(rules.year_plus_paternity_leave_days),  # Resets to 28
			}

			# Vacation Leave: Only after 5 years, receive full amount only once
			# Check if employee already received Vacation Leave in a previous year
			if tenure_years >= 5:
				# Check if employee already has Vacation Leave allocation in any previous year
				has_previous_vacation = frappe.db.exists(
					"Leave Allocation",
					{
						"employee": self.employee,
						"leave_type": "Vacation Leave",
						"docstatus": 1,
						"from_date": ("<", self.effective_from),
					},
				)
				# Only allocate if they haven't received it before
				if not has_previous_vacation:
					year_plus["Vacation Leave"] = flt(rules.year_plus_vacation_leave_days)

			leave_allocations.update(self.allocate_leaves_for_period(year_plus, date_of_joining))

		self.db_set("leaves_allocated", 1)
		return leave_allocations

	def carry_forward_monthly_leaves(self):
		"""
		Carry forward unused monthly leaves for employees in 6-12 month and 12+ month tenure brackets.
		This is called when creating a new MO Leave Policy Assignment.
		Rules:
		- Monthly Local Leave: Carry forward only (unused balance from previous year) - applies to both 6-12 and 12+
		- Monthly Sick Leave:
		  * 6-12 months: Carry forward on "Monthly Sick Leave" itself
		  * 12+ months: Reset to zero, unused balance moves to Bank Sick Leave (already handled in process_bank_leaves_from_previous_assignment)
		"""
		# Calculate previous year period (calendar year before current assignment year)
		current_year = getdate(self.effective_from).year
		previous_year = current_year - 1
		previous_period_start = getdate(f"{previous_year}-01-01")
		previous_period_end = getdate(f"{previous_year}-12-31")
		
		# Check if there are any ledger entries for monthly leaves in the previous year
		from frappe.query_builder.functions import Count
		LeaveLedgerEntry = frappe.qb.DocType("Leave Ledger Entry")
		
		has_previous_ledger_entries = (
			frappe.qb.from_(LeaveLedgerEntry)
			.select(Count(LeaveLedgerEntry.name))
			.where(
				(LeaveLedgerEntry.employee == self.employee)
				& (LeaveLedgerEntry.leave_type.isin(["Monthly Sick Leave", "Monthly Local Leave"]))
				& (LeaveLedgerEntry.from_date <= previous_period_end)
				& (LeaveLedgerEntry.to_date >= previous_period_start)
				& (LeaveLedgerEntry.docstatus == 1)
			)
		).run()[0][0] or 0
		
		if not has_previous_ledger_entries:
			# No previous monthly leaves to process
			return
		
		# Get unused monthly leaves from previous year
		monthly_sick_balance = self._get_unused_leave_balance_for_period(
			self.employee, "Monthly Sick Leave", previous_period_start, previous_period_end
		)
		monthly_local_balance = self._get_unused_leave_balance_for_period(
			self.employee, "Monthly Local Leave", previous_period_start, previous_period_end
		)

		# Determine tenure to handle Monthly Sick Leave correctly
		date_of_joining = frappe.db.get_value("Employee", self.employee, "date_of_joining")
		tenure_months = self.calculate_tenure_months(date_of_joining, self.effective_from) if date_of_joining else 0
		
		# Monthly Local Leave: Carry forward only (for both 6-12 and 12+ employees)
		if monthly_local_balance > 0:
			self._add_carried_forward_leaves("Monthly Local Leave", monthly_local_balance)
		
		# Monthly Sick Leave: Different rules based on tenure
		if monthly_sick_balance > 0:
			if 6 <= tenure_months < 12:
				# 6-12 months: Carry forward on "Monthly Sick Leave" itself
				self._add_carried_forward_leaves("Monthly Sick Leave", monthly_sick_balance)
			elif tenure_months >= 12:
				# 12+ months: Reset to zero, unused balance moves to Bank Sick Leave
				# This is already handled in process_bank_leaves_from_previous_assignment
				# (Monthly Sick Leave + Sick Leave both go to Bank Sick Leave)
				# So we don't need to do anything here for 12+ employees
				pass

	def _add_carried_forward_leaves(self, leave_type, carried_forward_amount):
		"""
		Add carried forward leaves to existing allocation or create new allocation.
		If an allocation already exists for this period, add the carried forward amount to it.
		Otherwise, create a new allocation with just the carried forward amount.
		"""
		# Check if allocation already exists for this period
		existing_allocation = frappe.db.get_value(
			"Leave Allocation",
			{
				"employee": self.employee,
				"leave_type": leave_type,
				"from_date": self.effective_from,
				"to_date": self.effective_to,
				"docstatus": 1,
			},
			"name",
		)

		if existing_allocation:
			# Update existing allocation by adding carried forward amount using the manual allocation method
			try:
				alloc_doc = frappe.get_doc("Leave Allocation", existing_allocation)
				# Use the allocate_leaves_manually method which handles ledger entries correctly
				alloc_doc.allocate_leaves_manually(
					new_leaves=flt(carried_forward_amount),
					from_date=self.effective_from,
				)
				
				frappe.msgprint(
					_("Added {0} carried forward {1} days to existing allocation").format(
						bold(carried_forward_amount), bold(leave_type)
					),
					indicator="green",
					title=_("Carry Forward Applied"),
				)
			except Exception as e:
				frappe.log_error(
					f"Failed to add carried forward {leave_type} for {self.employee}: {str(e)}",
					"MO Leave Policy Assignment - Carry Forward Error"
				)
		else:
			# Create new allocation with carried forward amount
			try:
				self.create_leave_allocation(leave_type, carried_forward_amount)
			except Exception as e:
				frappe.log_error(
					f"Failed to create carried forward {leave_type} allocation for {self.employee}: {str(e)}",
					"MO Leave Policy Assignment - Carry Forward Error"
				)

	def process_bank_leaves_from_previous_assignment(self):
		"""
		Process bank leave transfers from previous year.
		Only called for employees with 12+ months tenure.
		Handles the yearly reassignment logic:
		- Bank Sick Leave: (Monthly Sick Leave + Sick Leave) from previous year + existing Bank Sick Leave
		- Local Leave: Carries forward unused Local Leave from previous year (Bank Local Leave removed)
		"""
		# Import bank leave processing functions from utils module
		import hrms.hr.utils as hr_utils

		# Calculate previous year period (calendar year before current assignment year)
		current_year = getdate(self.effective_from).year
		previous_year = current_year - 1
		previous_period_start = getdate(f"{previous_year}-01-01")
		previous_period_end = getdate(f"{previous_year}-12-31")
		
		# Check if there are any ledger entries for the relevant leave types in the previous year
		from frappe.query_builder.functions import Count
		LeaveLedgerEntry = frappe.qb.DocType("Leave Ledger Entry")
		
		has_previous_ledger_entries = (
			frappe.qb.from_(LeaveLedgerEntry)
			.select(Count(LeaveLedgerEntry.name))
			.where(
				(LeaveLedgerEntry.employee == self.employee)
				& (LeaveLedgerEntry.leave_type.isin(["Monthly Sick Leave", "Sick Leave", "Local Leave"]))
				& (LeaveLedgerEntry.from_date <= previous_period_end)
				& (LeaveLedgerEntry.to_date >= previous_period_start)
				& (LeaveLedgerEntry.docstatus == 1)
			)
		).run()[0][0] or 0
		
		if not has_previous_ledger_entries:
			# No previous ledger entries found, nothing to transfer
			# But we still need to handle existing Bank Sick Leave (it accumulates)
			existing_bank_sick = hr_utils._get_leave_balance(self.employee, "Bank Sick Leave")
			if existing_bank_sick > 0:
				# Carry forward existing Bank Sick Leave
				self._create_or_update_bank_leave_allocation(
					"Bank Sick Leave",
					existing_bank_sick,
				)
			return

		# Get unused balances from previous year (at end of previous year)
		monthly_sick_balance = self._get_unused_leave_balance_for_period(
			self.employee, "Monthly Sick Leave", previous_period_start, previous_period_end
		)
		sick_leave_balance = self._get_unused_leave_balance_for_period(
			self.employee, "Sick Leave", previous_period_start, previous_period_end
		)

		# Process Bank Sick Leave: (Monthly Sick Leave + Sick Leave) from previous year + existing Bank Sick Leave
		bank_sick_from_previous_year = monthly_sick_balance + sick_leave_balance
		# Get existing Bank Sick Leave balance (accumulates - never resets)
		existing_bank_sick = hr_utils._get_leave_balance(self.employee, "Bank Sick Leave")
		new_bank_sick = existing_bank_sick + bank_sick_from_previous_year

		# Create or update allocation for Bank Sick Leave for the new period
		if new_bank_sick > 0:
			self._create_or_update_bank_leave_allocation(
				"Bank Sick Leave",
				new_bank_sick,
			)

		# Local Leave now carries forward (Bank Local Leave removed)
		# This will be handled in the main allocation logic where Local Leave = Carry Forward + 22

	def _get_unused_leave_balance_for_period(self, employee, leave_type, period_start, period_end):
		"""
		Get unused leave balance at the end of a specific period.
		Calculates the balance by summing all ledger entries that were active during the period
		and ended on or before period_end.
		The ledger balance (sum of all ledger entries) already accounts for allocations and usage.
		"""
		from frappe.query_builder.functions import Sum
		
		LeaveLedgerEntry = frappe.qb.DocType("Leave Ledger Entry")

		# Get the leave balance at the end of the period using the ledger
		# Sum all ledger entries that:
		# 1. Were active during the period (from_date <= period_end AND to_date >= period_start)
		# 2. Ended on or before period_end (to_date <= period_end)
		# 3. Are not expired
		# 4. Are submitted
		ledger_balance = (
			frappe.qb.from_(LeaveLedgerEntry)
			.select(Sum(LeaveLedgerEntry.leaves))
			.where(
				(LeaveLedgerEntry.employee == employee)
				& (LeaveLedgerEntry.leave_type == leave_type)
				& (LeaveLedgerEntry.from_date <= period_end)
				& (LeaveLedgerEntry.to_date >= period_start)
				& (LeaveLedgerEntry.to_date <= period_end)
				& (LeaveLedgerEntry.is_expired == 0)
				& (LeaveLedgerEntry.docstatus == 1)
			)
		).run()[0][0] or 0

		# The ledger balance already accounts for allocations and usage
		# Positive balance = unused leaves
		return max(0, flt(ledger_balance))

	def calculate_tenure_months(self, date_of_joining, effective_from):
		"""Calculate tenure in months from joining date to effective from date"""
		return self.calculate_tenure_months_static(date_of_joining, effective_from)

	@staticmethod
	def calculate_tenure_months_static(date_of_joining, effective_from):
		"""Static method to calculate tenure in months from joining date to effective from date"""
		doj = getdate(date_of_joining)
		eff_from = getdate(effective_from)
		
		# Calculate months difference
		months = (eff_from.year - doj.year) * 12 + (eff_from.month - doj.month)
		
		# Adjust if day of month is before joining day
		if eff_from.day < doj.day:
			months -= 1
		
		return max(0, months)

	def _create_or_update_bank_leave_allocation(self, leave_type, new_leaves):
		"""Create or update bank leave allocation for the current assignment period"""
		# Check if allocation already exists for this period
		existing_allocation = frappe.db.get_value(
			"Leave Allocation",
			{
				"employee": self.employee,
				"leave_type": leave_type,
				"from_date": self.effective_from,
				"to_date": self.effective_to,
				"docstatus": 1,
			},
			"name",
		)

		if existing_allocation:
			# Update existing allocation
			allocation = frappe.get_doc("Leave Allocation", existing_allocation)
			allocation.new_leaves_allocated = new_leaves
			allocation.total_leaves_allocated = new_leaves
			allocation.description = f"Bank leave allocation from MO Leave Policy Assignment {self.name}"
			allocation.save(ignore_permissions=True)
			allocation.submit()
		else:
			# Create new allocation
			import hrms.hr.utils as hr_utils
			hr_utils._create_bank_leave_allocation(
				self.employee,
				leave_type,
				new_leaves,
				self.effective_from,
				self.effective_to,
				description=f"Bank leave allocation from MO Leave Policy Assignment {self.name}",
			)

	def allocate_leaves_for_period(self, leave_rules, date_of_joining):
		"""Allocate leaves based on rules dictionary"""
		leave_allocations = {}
		
		for leave_type, allocation_amount in leave_rules.items():
			# Check if leave type exists
			if not frappe.db.exists("Leave Type", leave_type):
				frappe.log_error(
					f"Leave Type {leave_type} does not exist",
					"MO Leave Policy Assignment - Missing Leave Type"
				)
				continue

			# Skip Leave Without Pay types - they cannot be allocated
			is_lwp = frappe.db.get_value("Leave Type", leave_type, "is_lwp")
			if is_lwp:
				continue

			# Handle special cases
			if leave_type == "Maternity Leave" or leave_type == "Paternity Leave":
				allocation_amount = self.get_gender_based_allocation(leave_type)
				# Cap Maternity/Paternity leave to allocation period length if needed
				# These leaves can span periods, but we need to respect the validation
				allocation_amount = self.cap_allocation_to_period(leave_type, allocation_amount)
			elif leave_type == "Sick Leave":
				# Sick Leave: Reset to 15 per year (not prorated for yearly allocation)
				# Proration is only for daily scheduler allocations
				# For yearly allocation, it's always the full reset amount
				pass  # Use allocation_amount as-is (already set to 15)
			elif leave_type == "Local Leave":
				# Local Leave: Already includes carry forward + 22 in the allocation_amount
				# No need to prorate for yearly allocation
				pass  # Use allocation_amount as-is (already includes carry forward)

			# Create leave allocation (only for non-LWP types with allocation > 0)
			if allocation_amount > 0:
				leave_allocation, new_leaves_allocated = self.create_leave_allocation(
					leave_type, allocation_amount
				)
				leave_allocations[leave_type] = {
					"name": leave_allocation,
					"leaves": new_leaves_allocated,
				}

		return leave_allocations

	def get_gender_based_allocation(self, leave_type):
		"""Get allocation based on employee gender"""
		gender_link = frappe.db.get_value("Employee", self.employee, "gender")
		
		if not gender_link:
			return 0
		
		# Gender is a Link field to Gender doctype, get the gender name
		gender_name = frappe.db.get_value("Gender", gender_link, "gender")
		if not gender_name:
			return 0
		
		gender_lower = gender_name.lower()
		
		if leave_type == "Maternity Leave":
			# Check if gender is Female
			return 112 if gender_lower in ["female", "f"] else 0
		elif leave_type == "Paternity Leave":
			# Check if gender is Male
			return 28 if gender_lower in ["male", "m"] else 0
		return 0

	def _round_to_half(self, value):
		"""
		Round to 0.5 increments with custom rules:
		- 0 < x < 0.25 → 0
		- 0.25 ≤ x < 0.5 → 0.5
		- 0.5 ≤ x < 0.75 → 0.5
		- 0.75 ≤ x < 1.0 → 1
		"""
		import math
		integer_part = math.floor(value)
		decimal_part = value - integer_part
		
		if decimal_part == 0:
			return flt(integer_part)
		elif 0 < decimal_part < 0.25:
			return flt(integer_part)
		elif 0.25 <= decimal_part < 0.5:
			return flt(integer_part + 0.5)
		elif 0.5 <= decimal_part < 0.75:
			return flt(integer_part + 0.5)
		elif 0.75 <= decimal_part < 1.0:
			return flt(integer_part + 1.0)
		else:
			# Should not happen, but fallback to standard rounding
			return flt(rounded(value))

	def calculate_prorated_annual_leave(self, date_of_joining, annual_allocation):
		"""
		Prorate an annual allocation based on remaining months from one-year anniversary to period end.
		Formula: Prorated Leave = (Annual Leave ÷ 12) × Remaining Months
		Result is rounded to 0.5 increments using custom rounding rules.
		"""
		doj = getdate(date_of_joining)
		period_from = getdate(self.effective_from)
		period_to = getdate(self.effective_to)
		
		# Calculate one-year anniversary date
		one_year_anniversary = getdate(f"{doj.year + 1}-{doj.month:02d}-{doj.day:02d}")
		
		# If anniversary is after period start, calculate remaining months
		if one_year_anniversary > period_from:
			# Calculate remaining months from anniversary to period end
			from dateutil.relativedelta import relativedelta
			
			# Calculate months between anniversary and period end
			delta = relativedelta(period_to, one_year_anniversary)
			remaining_months = delta.years * 12 + delta.months
			
			# Add fractional month if there are remaining days
			if delta.days > 0:
				# Calculate days in the month containing the anniversary date
				if one_year_anniversary.month == 12:
					last_day_of_month = getdate(f"{one_year_anniversary.year + 1}-01-01") - relativedelta(days=1)
				else:
					last_day_of_month = getdate(f"{one_year_anniversary.year}-{one_year_anniversary.month + 1:02d}-01") - relativedelta(days=1)
				days_in_anniversary_month = last_day_of_month.day
				
				# If we're still in the same month, use days in that month
				if one_year_anniversary.month == period_to.month and one_year_anniversary.year == period_to.year:
					days_in_month = days_in_anniversary_month
				else:
					# Use days in the month of the period end
					if period_to.month == 12:
						last_day_of_end_month = getdate(f"{period_to.year + 1}-01-01") - relativedelta(days=1)
					else:
						last_day_of_end_month = getdate(f"{period_to.year}-{period_to.month + 1:02d}-01") - relativedelta(days=1)
					days_in_month = last_day_of_end_month.day
				
				# Add fractional month
				remaining_months += flt(delta.days) / flt(days_in_month)
			
			# Apply formula: (Annual Leave ÷ 12) × Remaining Months
			prorated = (flt(annual_allocation) / 12.0) * remaining_months
			# Apply custom rounding to 0.5 increments
			return self._round_to_half(prorated)
		
		# If anniversary is before or on period start, employee gets full allocation
		return flt(annual_allocation)

	def cap_allocation_to_period(self, leave_type, allocation_amount):
		"""
		Cap allocation amount to the number of days in the allocation period if needed.
		This prevents validation errors when allocated days exceed period length.
		Used for Maternity/Paternity leaves which may be allocated for periods shorter than the leave duration.
		If the leave type allows over-allocation, we don't cap it.
		"""
		# Check if leave type allows over-allocation
		allow_over_allocation = frappe.db.get_value("Leave Type", leave_type, "allow_over_allocation")
		
		if allow_over_allocation:
			# Leave type allows over-allocation, so we can allocate the full amount
			return flt(allocation_amount)
		
		# Check if allocation exceeds period length
		period_from = getdate(self.effective_from)
		period_to = getdate(self.effective_to)
		days_in_period = date_diff(period_to, period_from) + 1
		
		# If allocation exceeds period length and over-allocation is not allowed, cap it
		if allocation_amount > days_in_period:
			frappe.msgprint(
				_(
					"{0} allocation ({1} days) exceeds allocation period length ({2} days). "
					"Capping to {2} days. To allow full allocation, enable 'Allow Over Allocation' "
					"for the {0} leave type."
				).format(
					bold(leave_type),
					bold(allocation_amount),
					bold(days_in_period),
					bold(days_in_period)
				),
				indicator="orange",
				title=_("Allocation Capped"),
			)
			return flt(days_in_period)
		
		return flt(allocation_amount)

	def create_leave_allocation(self, leave_type, new_leaves_allocated):
		"""Create Leave Allocation document"""
		from frappe.model.meta import get_field_precision
		
		precision = get_field_precision(
			frappe.get_meta("Leave Allocation").get_field("new_leaves_allocated")
		)
		
		new_leaves_allocated = flt(new_leaves_allocated, precision)
		
		# Check for existing overlapping allocation
		existing_allocation = frappe.db.get_value(
			"Leave Allocation",
			{
				"employee": self.employee,
				"leave_type": leave_type,
				"docstatus": 1,
				"from_date": ("<=", self.effective_to),
				"to_date": (">=", self.effective_from),
			},
			["name", "from_date", "to_date", "leave_policy_assignment", "description"],
			as_dict=True,
		)
		
		if existing_allocation:
			# Check if it's from a regular Leave Policy Assignment
			if existing_allocation.leave_policy_assignment:
				if frappe.db.exists("Leave Policy Assignment", existing_allocation.leave_policy_assignment):
					frappe.throw(
						_(
							"Cannot create MO Leave Allocation for {0}. Employee already has a Leave Allocation "
							"for {1} (Period: {2} to {3}) from regular Leave Policy Assignment {4}. "
							"Please cancel or delete the regular Leave Policy Assignment first."
						).format(
							bold(leave_type),
							bold(leave_type),
							bold(formatdate(existing_allocation.from_date)),
							bold(formatdate(existing_allocation.to_date)),
							bold(existing_allocation.leave_policy_assignment),
						),
						title=_("Allocation Overlap"),
					)
			
			# Check if it's from a previous MO assignment (by checking description)
			desc = existing_allocation.get("description", "") or ""
			if "MO Leave Policy Assignment" in desc or "Assignment:" in desc:
				# It's from an MO assignment - this should have been prevented by validate_assignment_overlap
				# But if we're here, it means there's a duplicate. Cancel the old allocation first.
				try:
					old_alloc_doc = frappe.get_doc("Leave Allocation", existing_allocation.name)
					if old_alloc_doc.docstatus == 1:
						old_alloc_doc.cancel()
						frappe.db.commit()
						frappe.msgprint(
							_("Cancelled existing {0} allocation {1} from previous MO assignment").format(
								bold(leave_type), bold(existing_allocation.name)
							),
							indicator="orange",
							title=_("Previous Allocation Cancelled"),
						)
				except Exception as e:
					frappe.throw(
						_(
							"Cannot create Leave Allocation for {0}. Overlapping allocation {1} exists "
							"(Period: {2} to {3}). Please cancel the previous MO Leave Policy Assignment first."
						).format(
							bold(leave_type),
							bold(existing_allocation.name),
							bold(formatdate(existing_allocation.from_date)),
							bold(formatdate(existing_allocation.to_date)),
						),
						title=_("Allocation Overlap"),
					)
			else:
				# Unknown source, throw error
				frappe.throw(
					_(
						"Cannot create Leave Allocation for {0}. Overlapping allocation {1} exists "
						"(Period: {2} to {3})"
					).format(
						bold(leave_type),
						bold(existing_allocation.name),
						bold(formatdate(existing_allocation.from_date)),
						bold(formatdate(existing_allocation.to_date)),
					),
					title=_("Allocation Overlap"),
				)
		
		try:
			allocation = frappe.get_doc(
				dict(
					doctype="Leave Allocation",
					employee=self.employee,
					leave_type=leave_type,
					from_date=self.effective_from,
					to_date=self.effective_to,
					new_leaves_allocated=new_leaves_allocated,
					description=f"Allocated via MO Leave Policy Assignment: {self.name}",
					carry_forward=0,  # MO leaves don't use standard carry forward
				)
			)
			allocation.save(ignore_permissions=True)
			allocation.submit()
			return allocation.name, new_leaves_allocated
		except frappe.exceptions.ValidationError as e:
			# Extract the actual error message, removing document references
			error_msg = str(e)
			# Remove "Reference: DOCNAME" pattern if present
			import re
			error_msg = re.sub(r'\s*Reference:\s*[A-Z0-9-]+\s*', '', error_msg)
			frappe.throw(
				_("Cannot create Leave Allocation for {0}: {1}").format(bold(leave_type), error_msg),
				title=_("Allocation Error"),
			)
		except Exception as e:
			# Provide clearer error message for other exceptions
			error_msg = str(e)
			# Remove "Reference: DOCNAME" pattern if present
			import re
			error_msg = re.sub(r'\s*Reference:\s*[A-Z0-9-]+\s*', '', error_msg)
			if "overlap" in error_msg.lower() or "already exists" in error_msg.lower():
				frappe.throw(
					_("Cannot create Leave Allocation for {0}: {1}").format(bold(leave_type), error_msg),
					title=_("Allocation Error"),
				)
			else:
				# Log the full error for debugging
				frappe.log_error(
					f"Error creating Leave Allocation for {leave_type} (Employee: {self.employee}): {str(e)}",
					"MO Leave Policy Assignment - Leave Allocation Error"
				)
				frappe.throw(
					_("Cannot create Leave Allocation for {0}: {1}").format(bold(leave_type), error_msg),
					title=_("Allocation Error"),
				)
