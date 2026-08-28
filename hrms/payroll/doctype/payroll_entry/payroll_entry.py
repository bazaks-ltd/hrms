# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

from dateutil.relativedelta import relativedelta

import frappe
from frappe import _
from frappe.desk.reportview import get_match_cond
from frappe.model.document import Document
from frappe.query_builder.functions import Coalesce, Count
from frappe.utils import (
	DATE_FORMAT,
	add_days,
	add_to_date,
	cint,
	comma_and,
	date_diff,
	flt,
	get_link_to_form,
	getdate,
)

import erpnext
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)
from erpnext.accounts.utils import get_fiscal_year


class PayrollEntry(Document):
	def onload(self):
		# if not self.docstatus == 1 or self.salary_slips_submitted:
		if not self.docstatus == 1:
			return

		# check if salary slips were manually submitted
		# Check if there are NO draft salary slips (simpler than counting, handles employees who left)
		draft_count = frappe.db.count("Salary Slip", {"payroll_entry": self.name, "docstatus": 0})
		if cint(draft_count) == 0:
			self.set_onload("submitted_ss", True)

		je = frappe.db.count("Journal Entry Account", {"reference_name": self.name, "docstatus": 1}, ["name"])
		if cint(je) > 0:
			self.set_onload("submitted_je", True)

	def validate(self):
		self.number_of_employees = len(self.employees)
		self.set_status()

	def set_status(self, status=None, update=False):
		if not status:
			if self.docstatus == 1 and self.status in ("Completed", "Queued", "Failed"):
				status = self.status
			else:
				status = {0: "Draft", 1: "Submitted", 2: "Cancelled"}[self.docstatus or 0]

		if update:
			self.db_set("status", status)
		else:
			self.status = status

	def before_submit(self):
		self.validate_existing_salary_slips()
		self.validate_payroll_payable_account()
		if self.get_employees_with_unmarked_attendance():
			frappe.throw(_("Cannot submit. Attendance is not marked for some employees."))

	def on_submit(self):
		self.set_status(update=True, status="Submitted")
		self.create_salary_slips()

	def validate_existing_salary_slips(self):
		if not self.employees:
			return

		existing_salary_slips = []
		SalarySlip = frappe.qb.DocType("Salary Slip")

		existing_salary_slips = (
			frappe.qb.from_(SalarySlip)
			.select(SalarySlip.employee, SalarySlip.name)
			.where(
				(SalarySlip.employee.isin([emp.employee for emp in self.employees]))
				& (SalarySlip.start_date == self.start_date)
				& (SalarySlip.end_date == self.end_date)
				& (SalarySlip.docstatus != 2)
			)
		).run(as_dict=True)

		if len(existing_salary_slips):
			msg = _("Salary Slip already exists for {0} for the given dates").format(
				comma_and([frappe.bold(d.employee) for d in existing_salary_slips])
			)
			msg += "<br><br>"
			msg += _("Reference: {0}").format(
				comma_and([get_link_to_form("Salary Slip", d.name) for d in existing_salary_slips])
			)
			frappe.throw(
				msg,
				title=_("Duplicate Entry"),
			)

	def validate_payroll_payable_account(self):
		if frappe.db.get_value("Account", self.payroll_payable_account, "account_type"):
			frappe.throw(
				_(
					"Account type cannot be set for payroll payable account {0}, please remove and try again"
				).format(frappe.bold(get_link_to_form("Account", self.payroll_payable_account)))
			)

	def on_cancel(self):
		self.ignore_linked_doctypes = ("GL Entry", "Salary Slip", "Journal Entry")

		self.delete_linked_salary_slips()
		self.cancel_linked_journal_entries()

		# reset flags & update status
		self.db_set("salary_slips_created", 0)
		self.db_set("salary_slips_submitted", 0)
		self.db_set("payslips_reviewed", 0)
		self.set_status(update=True, status="Cancelled")
		self.db_set("error_message", "")

	def cancel(self):
		if len(self.get_linked_salary_slips()) > 50:
			msg = _("Payroll Entry cancellation is queued. It may take a few minutes")
			msg += "<br>"
			msg += _(
				"In case of any error during this background process, the system will add a comment about the error on this Payroll Entry and revert to the Submitted status"
			)
			frappe.msgprint(
				msg,
				indicator="blue",
				title=_("Cancellation Queued"),
			)
			self.queue_action("cancel", timeout=3000)
		else:
			self._cancel()

	def delete_linked_salary_slips(self):
		salary_slips = self.get_linked_salary_slips()

		# cancel & delete salary slips
		for salary_slip in salary_slips:
			if salary_slip.docstatus == 1:
				frappe.get_doc("Salary Slip", salary_slip.name).cancel()
			frappe.delete_doc("Salary Slip", salary_slip.name)

	def cancel_linked_journal_entries(self):
		journal_entries = frappe.get_all(
			"Journal Entry Account",
			{"reference_type": self.doctype, "reference_name": self.name, "docstatus": 1},
			pluck="parent",
			distinct=True,
		)

		# cancel Journal Entries
		for je in journal_entries:
			frappe.get_doc("Journal Entry", je).cancel()

	def get_linked_salary_slips(self):
		return frappe.get_all("Salary Slip", {"payroll_entry": self.name}, ["name", "docstatus"])

	def make_filters(self):
		filters = frappe._dict(
			company=self.company,
			branch=self.branch,
			department=self.department,
			designation=self.designation,
			grade=self.grade,
			currency=self.currency,
			start_date=self.start_date,
			end_date=self.end_date,
			payroll_payable_account=self.payroll_payable_account,
			salary_slip_based_on_timesheet=self.salary_slip_based_on_timesheet,
		)

		if not self.salary_slip_based_on_timesheet:
			filters.update(dict(payroll_frequency=self.payroll_frequency))

		return filters

	@frappe.whitelist()
	def fill_employee_details(self):
		filters = self.make_filters()
		employees = get_employee_list(filters=filters, as_dict=True, ignore_match_conditions=True)
		self.set("employees", [])

		if not employees:
			error_msg = _(
				"No employees found for the mentioned criteria:<br>Company: {0}<br> Currency: {1}<br>Payroll Payable Account: {2}"
			).format(
				frappe.bold(self.company),
				frappe.bold(self.currency),
				frappe.bold(self.payroll_payable_account),
			)
			if self.branch:
				error_msg += "<br>" + _("Branch: {0}").format(frappe.bold(self.branch))
			if self.department:
				error_msg += "<br>" + _("Department: {0}").format(frappe.bold(self.department))
			if self.designation:
				error_msg += "<br>" + _("Designation: {0}").format(frappe.bold(self.designation))
			if self.start_date:
				error_msg += "<br>" + _("Start date: {0}").format(frappe.bold(self.start_date))
			if self.end_date:
				error_msg += "<br>" + _("End date: {0}").format(frappe.bold(self.end_date))
			frappe.throw(error_msg, title=_("No employees found"))

		self.set("employees", employees)
		self.number_of_employees = len(self.employees)

		return self.get_employees_with_unmarked_attendance()

	@frappe.whitelist()
	def create_salary_slips(self):
		"""
		Creates salary slip for selected employees if already not created
		"""
		self.check_permission("write")
		employees = [emp.employee for emp in self.employees]

		if employees:
			args = frappe._dict(
				{
					"salary_slip_based_on_timesheet": self.salary_slip_based_on_timesheet,
					"payroll_frequency": self.payroll_frequency,
					"start_date": self.start_date,
					"end_date": self.end_date,
					"company": self.company,
					"posting_date": self.posting_date,
					"deduct_tax_for_unclaimed_employee_benefits": self.deduct_tax_for_unclaimed_employee_benefits,
					"deduct_tax_for_unsubmitted_tax_exemption_proof": self.deduct_tax_for_unsubmitted_tax_exemption_proof,
					"payroll_entry": self.name,
					"exchange_rate": self.exchange_rate,
					"currency": self.currency,
				}
			)
			if len(employees) > 30 or frappe.flags.enqueue_payroll_entry:
				self.db_set("status", "Queued")
				frappe.enqueue(
					create_salary_slips_for_employees,
					timeout=3000,
					employees=employees,
					args=args,
					publish_progress=False,
				)
				frappe.msgprint(
					_("Salary Slip creation is queued. It may take a few minutes"),
					alert=True,
					indicator="blue",
				)
			else:
				create_salary_slips_for_employees(employees, args, publish_progress=False)
				# since this method is called via frm.call this doc needs to be updated manually
				self.reload()

	def get_sal_slip_list(self, ss_status, as_dict=False):
		"""
		Returns list of salary slips based on selected criteria
		"""

		ss = frappe.qb.DocType("Salary Slip")
		ss_list = (
			frappe.qb.from_(ss)
			.select(ss.name, ss.salary_structure)
			.where(
				(ss.docstatus == ss_status)
				& (ss.start_date >= self.start_date)
				& (ss.end_date <= self.end_date)
				& (ss.payroll_entry == self.name)
				& ((ss.journal_entry.isnull()) | (ss.journal_entry == ""))
				& (Coalesce(ss.salary_slip_based_on_timesheet, 0) == self.salary_slip_based_on_timesheet)
			)
		).run(as_dict=as_dict)

		return ss_list

	@frappe.whitelist()
	def submit_salary_slips(self):
		self.check_permission("write")
		salary_slips = self.get_sal_slip_list(ss_status=0)

		if len(salary_slips) > 30 or frappe.flags.enqueue_payroll_entry:
			self.db_set("status", "Queued")
			frappe.enqueue(
				submit_salary_slips_for_employees,
				timeout=3000,
				payroll_entry=self,
				salary_slips=salary_slips,
				publish_progress=False,
			)
			frappe.msgprint(
				_("Salary Slip submission is queued. It may take a few minutes"),
				alert=True,
				indicator="blue",
			)
		else:
			submit_salary_slips_for_employees(self, salary_slips, publish_progress=False)

	def email_salary_slip(self, submitted_ss):
		if frappe.db.get_single_value("Payroll Settings", "email_salary_slip_to_employee"):
			for ss in submitted_ss:
				# Handle both dict and document objects
				if isinstance(ss, dict):
					# Get document object from dict
					salary_slip = frappe.get_doc("Salary Slip", ss.get("name"))
				else:
					# Already a document object
					salary_slip = ss
				salary_slip.email_salary_slip()

	def get_salary_component_account(self, salary_component):
		account = frappe.db.get_value(
			"Salary Component Account",
			{"parent": salary_component, "company": self.company},
			"account",
			cache=True,
		)

		if not account:
			frappe.throw(
				_("Please set account in Salary Component {0}").format(
					get_link_to_form("Salary Component", salary_component)
				)
			)

		return account

	def get_salary_components(self, component_type):
		salary_slips = self.get_sal_slip_list(ss_status=1, as_dict=True)

		if salary_slips:
			ss = frappe.qb.DocType("Salary Slip")
			ssd = frappe.qb.DocType("Salary Detail")
			salary_components = (
				frappe.qb.from_(ss)
				.join(ssd)
				.on(ss.name == ssd.parent)
				.select(
					ssd.salary_component,
					ssd.amount,
					ssd.parentfield,
					ssd.additional_salary,
					ss.salary_structure,
					ss.employee,
					ssd.do_not_include_in_total,
				)
				.where((ssd.parentfield == component_type) & (ss.name.isin([d.name for d in salary_slips])))
			).run(as_dict=True)

			return salary_components

	def get_salary_component_total(
		self,
		component_type=None,
		employee_wise_accounting_enabled=False,
	):
		salary_components = self.get_salary_components(component_type)
		if salary_components:
			component_dict = {}

			for item in salary_components:
				if not self.should_add_component_to_accrual_jv(component_type, item):
					continue

				employee_cost_centers = self.get_payroll_cost_centers_for_employee(
					item.employee, item.salary_structure
				)
				employee_advance = self.get_advance_deduction(component_type, item)

				for cost_center, percentage in employee_cost_centers.items():
					amount_against_cost_center = flt(item.amount) * percentage / 100

					if employee_advance:
						self.add_advance_deduction_entry(
							item, amount_against_cost_center, cost_center, employee_advance
						)
					else:
						key = (item.salary_component, cost_center, item.do_not_include_in_total)
						component_dict[key] = component_dict.get(key, 0) + amount_against_cost_center
						

					if employee_wise_accounting_enabled:
						self.set_employee_based_payroll_payable_entries(
							component_type, item.employee, amount_against_cost_center
						)

			account_details = self.get_account(component_dict=component_dict)
			return account_details

	def should_add_component_to_accrual_jv(self, component_type: str, item: dict) -> bool:
		add_component_to_accrual_jv = True
		if component_type == "earnings":
			is_flexible_benefit, only_tax_impact = frappe.get_cached_value(
				"Salary Component", item["salary_component"], ["is_flexible_benefit", "only_tax_impact"]
			)
			if cint(is_flexible_benefit) and cint(only_tax_impact):
				add_component_to_accrual_jv = False

		return add_component_to_accrual_jv

	def get_advance_deduction(self, component_type: str, item: dict) -> str | None:
		if component_type == "deductions" and item.additional_salary:
			ref_doctype, ref_docname = frappe.db.get_value(
				"Additional Salary",
				item.additional_salary,
				["ref_doctype", "ref_docname"],
			)

			if ref_doctype == "Employee Advance":
				return ref_docname
		return

	def add_advance_deduction_entry(
		self,
		item: dict,
		amount: float,
		cost_center: str,
		employee_advance: str,
	) -> None:
		self._advance_deduction_entries.append(
			{
				"employee": item.employee,
				"account": self.get_salary_component_account(item.salary_component),
				"amount": amount,
				"cost_center": cost_center,
				"reference_type": "Employee Advance",
				"reference_name": employee_advance,
			}
		)

	def set_accounting_entries_for_advance_deductions(
		self,
		accounts: list,
		currencies: list,
		company_currency: str,
		accounting_dimensions: list,
		precision: int,
		payable_amount: float,
	):
		for entry in self._advance_deduction_entries:
			payable_amount = self.get_accounting_entries_and_payable_amount(
				entry.get("account"),
				entry.get("cost_center"),
				entry.get("amount"),
				currencies,
				company_currency,
				payable_amount,
				accounting_dimensions,
				precision,
				entry_type="credit",
				accounts=accounts,
				party=entry.get("employee"),
				reference_type="Employee Advance",
				reference_name=entry.get("reference_name"),
				is_advance="Yes",
			)

		return payable_amount

	def set_employee_based_payroll_payable_entries(
		self, component_type, employee, amount, salary_structure=None
	):
		employee_details = self.employee_based_payroll_payable_entries.setdefault(employee, {})

		employee_details.setdefault(component_type, 0)
		employee_details[component_type] += amount

		if salary_structure and "salary_structure" not in employee_details:
			employee_details["salary_structure"] = salary_structure

	def get_payroll_cost_centers_for_employee(self, employee, salary_structure):
		if not hasattr(self, "employee_cost_centers"):
			self.employee_cost_centers = {}

		if not self.employee_cost_centers.get(employee):
			SalaryStructureAssignment = frappe.qb.DocType("Salary Structure Assignment")
			EmployeeCostCenter = frappe.qb.DocType("Employee Cost Center")

			cost_centers = dict(
				(
					frappe.qb.from_(SalaryStructureAssignment)
					.join(EmployeeCostCenter)
					.on(SalaryStructureAssignment.name == EmployeeCostCenter.parent)
					.select(EmployeeCostCenter.cost_center, EmployeeCostCenter.percentage)
					.where(
						(SalaryStructureAssignment.employee == employee)
						& (SalaryStructureAssignment.docstatus == 1)
						& (SalaryStructureAssignment.salary_structure == salary_structure)
					)
				).run(as_list=True)
			)

			if not cost_centers:
				default_cost_center, department = frappe.get_cached_value(
					"Employee", employee, ["payroll_cost_center", "department"]
				)

				if not default_cost_center and department:
					default_cost_center = frappe.get_cached_value(
						"Department", department, "payroll_cost_center"
					)

				if not default_cost_center:
					default_cost_center = self.cost_center

				cost_centers = {default_cost_center: 100}

			self.employee_cost_centers.setdefault(employee, cost_centers)

		return self.employee_cost_centers.get(employee, {})

	def get_account(self, component_dict=None):
		account_dict = {}
		for key, amount in component_dict.items():
			component, cost_center, do_not_include_in_total = key
			account = self.get_salary_component_account(component)
			accounting_key = (account, cost_center, do_not_include_in_total)

			account_dict[accounting_key] = account_dict.get(accounting_key, 0) + amount

		return account_dict

	def make_accrual_jv_entry(self, submitted_salary_slips):

		self.check_permission("write")
		employee_wise_accounting_enabled = frappe.db.get_single_value(
			"Payroll Settings", "process_payroll_accounting_entry_based_on_employee"
		)
		self.employee_based_payroll_payable_entries = {}
		self._advance_deduction_entries = []
		
		earnings = (
			self.get_salary_component_total(
				component_type="earnings",
				employee_wise_accounting_enabled=employee_wise_accounting_enabled,
			)
			or {}
		)

		deductions = (
			self.get_salary_component_total(
				component_type="deductions",
				employee_wise_accounting_enabled=employee_wise_accounting_enabled,
			)
			or {}
		)

		precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")

		if earnings or deductions:
			accounts = []
			currencies = []
			payable_amount = 0
			accounting_dimensions = get_accounting_dimensions() or []
			company_currency = erpnext.get_company_currency(self.company)
			
			payable_amount = self.get_payable_amount_for_earnings_and_deductions(
				accounts,
				earnings,
				deductions,
				currencies,
				company_currency,
				accounting_dimensions,
				precision,
				payable_amount,
			)

			payable_amount = self.set_accounting_entries_for_advance_deductions(
				accounts,
				currencies,
				company_currency,
				accounting_dimensions,
				precision,
				payable_amount,
			)

			self.set_payable_amount_against_payroll_payable_account(
				accounts,
				currencies,
				company_currency,
				accounting_dimensions,
				precision,
				payable_amount,
				self.payroll_payable_account,
				employee_wise_accounting_enabled,
			)

			self.payable_amount = payable_amount
			
			
			
			mra_accounts = ['NSF', 'LEVY', 'CSG', 'PRGF', 'PAYE']
			mra_amount = 0
			
			for account in accounts:
				if  'credit_in_account_currency' in account and account['credit_in_account_currency'] > 0:
					 if any(mra_account in account['account'] for mra_account in mra_accounts):
						 mra_amount += account['credit_in_account_currency']
									
			
			self.mra_amount = mra_amount
			self.submitted_mra = 0
			self.submitted_bank = 0
			self.db_update()
			self.make_journal_entry(
				accounts,
				currencies,
				self.payroll_payable_account,
				voucher_type="Journal Entry",
				user_remark=_("Accrual Journal Entry for salaries from {0} to {1}").format(
					self.start_date, self.end_date
				),
				submit_journal_entry=True,
				submitted_salary_slips=submitted_salary_slips,
			)

	def make_journal_entry(
		self,
		accounts,
		currencies,
		payroll_payable_account=None,
		voucher_type="Journal Entry",
		user_remark="",
		submitted_salary_slips: list | None = None,
		submit_journal_entry=False,
		cheque_no=None,
		cheque_date=None,
	):
		multi_currency = 0
		if len(currencies) > 1:
			multi_currency = 1

		journal_entry = frappe.new_doc("Journal Entry")
		journal_entry.voucher_type = voucher_type
		journal_entry.user_remark = user_remark
		journal_entry.company = self.company
		journal_entry.posting_date = self.posting_date
		if cheque_no:
			journal_entry.cheque_no = cheque_no
			journal_entry.cheque_date = cheque_date or self.posting_date

		journal_entry.set("accounts", accounts)
		journal_entry.multi_currency = multi_currency

		if voucher_type == "Journal Entry":
			journal_entry.title = payroll_payable_account

		journal_entry.save(ignore_permissions=True)

		try:
			if submit_journal_entry:
				journal_entry.submit()

			if submitted_salary_slips:
				self.update_salary_slip_status(submitted_salary_slips, jv_name=journal_entry.name)

		except Exception as e:
			if type(e) in (str, list, tuple):
				frappe.msgprint(e)

			self.log_error("Journal Entry creation against Salary Slip failed")
			raise

	@staticmethod
	def is_cheque_mode(mode_of_payment) -> bool:
		"""Match Doctors Pay: Mode of Payment named exactly 'Cheque'."""
		return (mode_of_payment or "").strip() == "Cheque"

	def get_payable_amount_for_earnings_and_deductions(
		self,
		accounts,
		earnings,
		deductions,
		currencies,
		company_currency,
		accounting_dimensions,
		precision,
		payable_amount,
	):
		# Earnings
		for acc_cc, amount in earnings.items():
			# we need accrued only earnings with do_not_include_in_total = 0
			if acc_cc[2]:
				payable_amount = self.get_accounting_entries_and_payable_amount(
					acc_cc[0],
					acc_cc[1] or self.cost_center,
					amount,
					currencies,
					company_currency,
					payable_amount,
					accounting_dimensions,
					precision,
					entry_type="debit",
					accounts=accounts,
				)

				payable_amount = self.get_accounting_entries_and_payable_amount(
					f'Accrued - {acc_cc[0]}',
					acc_cc[1] or self.cost_center,
					amount,
					currencies,
					company_currency,
					payable_amount,
					accounting_dimensions,
					precision,
					entry_type="credit",
					accounts=accounts,
				)
			else:
				payable_amount = self.get_accounting_entries_and_payable_amount(
					acc_cc[0],
					acc_cc[1] or self.cost_center,
					amount,
					currencies,
					company_currency,
					payable_amount,
					accounting_dimensions,
					precision,
					entry_type="debit",
					accounts=accounts,
				)


		# Deductions
		for acc_cc, amount in deductions.items():
			payable_amount = self.get_accounting_entries_and_payable_amount(
				acc_cc[0],
				acc_cc[1] or self.cost_center,
				amount,
				currencies,
				company_currency,
				payable_amount,
				accounting_dimensions,
				precision,
				entry_type="credit",
				accounts=accounts,
			)

		return payable_amount

	def set_payable_amount_against_payroll_payable_account(
		self,
		accounts,
		currencies,
		company_currency,
		accounting_dimensions,
		precision,
		payable_amount,
		payroll_payable_account,
		employee_wise_accounting_enabled,
	):
		# Payable amount
		if employee_wise_accounting_enabled:
			"""
			employee_based_payroll_payable_entries = {
			                'HREMP00004': {
			                                'earnings': 83332.0,
			                                'deductions': 2000.0
			                },
			                'HREMP00005': {
			                                'earnings': 50000.0,
			                                'deductions': 2000.0
			                }
			}
			"""
			for employee, employee_details in self.employee_based_payroll_payable_entries.items():
				payable_amount = employee_details.get("earnings", 0) - employee_details.get("deductions", 0)

				payable_amount = self.get_accounting_entries_and_payable_amount(
					payroll_payable_account,
					self.cost_center,
					payable_amount,
					currencies,
					company_currency,
					0,
					accounting_dimensions,
					precision,
					entry_type="payable",
					party=employee,
					accounts=accounts,
				)
		else:
			payable_amount = self.get_accounting_entries_and_payable_amount(
				payroll_payable_account,
				self.cost_center,
				payable_amount,
				currencies,
				company_currency,
				0,
				accounting_dimensions,
				precision,
				entry_type="payable",
				accounts=accounts,
			)

	def get_accounting_entries_and_payable_amount(
		self,
		account,
		cost_center,
		amount,
		currencies,
		company_currency,
		payable_amount,
		accounting_dimensions,
		precision,
		entry_type="credit",
		party=None,
		accounts=None,
		reference_type=None,
		reference_name=None,
		is_advance=None,
	):
		exchange_rate, amt = self.get_amount_and_exchange_rate_for_journal_entry(
			account, amount, company_currency, currencies
		)

		row = {
			"account": account,
			"exchange_rate": flt(exchange_rate),
			"cost_center": cost_center,
			"project": self.project,
		}

		if entry_type == "debit":
			payable_amount += flt(amount, precision)
			row.update(
				{
					"debit_in_account_currency": flt(amt, precision),
				}
			)
		elif entry_type == "credit":
			payable_amount -= flt(amount, precision)
			row.update(
				{
					"credit_in_account_currency": flt(amt, precision),
				}
			)
		else:
			row.update(
				{
					"credit_in_account_currency": flt(amt, precision),
					"reference_type": self.doctype,
					"reference_name": self.name,
				}
			)

		if party:
			row.update(
				{
					"party_type": "Employee",
					"party": party,
				}
			)

		if reference_type:
			row.update(
				{
					"reference_type": reference_type,
					"reference_name": reference_name,
					"is_advance": is_advance,
				}
			)

		self.update_accounting_dimensions(
			row,
			accounting_dimensions,
		)

		if amt:
			accounts.append(row)

		return payable_amount

	def update_accounting_dimensions(self, row, accounting_dimensions):
		for dimension in accounting_dimensions:
			row.update({dimension: self.get(dimension)})

		return row

	def get_amount_and_exchange_rate_for_journal_entry(self, account, amount, company_currency, currencies):
		conversion_rate = 1
		exchange_rate = self.exchange_rate
		account_currency = frappe.db.get_value("Account", account, "account_currency")

		if account_currency not in currencies:
			currencies.append(account_currency)

		if account_currency == company_currency:
			conversion_rate = self.exchange_rate
			exchange_rate = 1

		amount = flt(amount) * flt(conversion_rate)

		return exchange_rate, amount

	@frappe.whitelist()
	def make_bank_entry(self):
		self.check_permission("write")
		if not frappe.flags.skip_payroll_je_gate:
			self.validate_ready_for_journal_entries()
		if not self.payment_account:
			frappe.throw(_("Payment Account is mandatory to make Bank Entry"))

		slip_map = self.get_salary_slip_payment_map()
		self.validate_slips_ready_for_bank_entry(slip_map)

		self.employee_based_payroll_payable_entries = {}
		employee_wise_accounting_enabled = frappe.db.get_single_value(
			"Payroll Settings", "process_payroll_accounting_entry_based_on_employee"
		)

		salary_slip_total = 0
		salary_slips = self.get_salary_slip_details()

		for salary_detail in salary_slips:
			if salary_detail.parentfield == "earnings":
				(
					is_flexible_benefit,
					only_tax_impact,
					create_separate_je,
					statistical_component,
				) = frappe.db.get_value(
					"Salary Component",
					salary_detail.salary_component,
					(
						"is_flexible_benefit",
						"only_tax_impact",
						"create_separate_payment_entry_against_benefit_claim",
						"statistical_component",
					),
					cache=True,
				)

				if only_tax_impact != 1 and statistical_component != 1:
					if is_flexible_benefit == 1 and create_separate_je == 1:
						self.set_accounting_entries_for_bank_entry(
							salary_detail.amount, salary_detail.salary_component
						)
					else:
						if employee_wise_accounting_enabled:
							self.set_employee_based_payroll_payable_entries(
								"earnings",
								salary_detail.employee,
								salary_detail.amount,
								salary_detail.salary_structure,
							)
						salary_slip_total += salary_detail.amount

			if salary_detail.parentfield == "deductions":
				statistical_component = frappe.db.get_value(
					"Salary Component", salary_detail.salary_component, "statistical_component", cache=True
				)

				if not statistical_component:
					if employee_wise_accounting_enabled:
						self.set_employee_based_payroll_payable_entries(
							"deductions",
							salary_detail.employee,
							salary_detail.amount,
							salary_detail.salary_structure,
						)

					salary_slip_total -= salary_detail.amount

		if salary_slip_total <= 0 and not self.employee_based_payroll_payable_entries:
			return

		# Split bank-transfer (one bulk JE) vs cheque (one JE per slip, no employee party)
		bank_entries = {}
		cheque_payments = []
		bank_total = 0

		if employee_wise_accounting_enabled and self.employee_based_payroll_payable_entries:
			for employee, details in self.employee_based_payroll_payable_entries.items():
				amount = flt(details.get("earnings", 0)) - flt(details.get("deductions", 0))
				if amount <= 0:
					continue
				slip = slip_map.get(employee) or {}
				if self.is_cheque_mode(slip.get("mode_of_payment")):
					cheque_payments.append(
						{
							"employee": employee,
							"amount": amount,
							"salary_slip": slip.get("name"),
							"payment_reference_no": slip.get("payment_reference_no"),
						}
					)
				else:
					bank_entries[employee] = details
					bank_total += amount
		else:
			for employee, slip in slip_map.items():
				amount = flt(slip.get("net_pay"))
				if amount <= 0:
					continue
				if self.is_cheque_mode(slip.get("mode_of_payment")):
					cheque_payments.append(
						{
							"employee": employee,
							"amount": amount,
							"salary_slip": slip.get("name"),
							"payment_reference_no": slip.get("payment_reference_no"),
						}
					)
				else:
					bank_total += amount

		if bank_total > 0:
			original_employee_entries = self.employee_based_payroll_payable_entries
			try:
				self.employee_based_payroll_payable_entries = (
					bank_entries if employee_wise_accounting_enabled else {}
				)
				# When not employee-wise, use bank_total; when employee-wise, amount is recomputed from map
				je_amount = bank_total if not employee_wise_accounting_enabled else bank_total
				self.set_accounting_entries_for_bank_entry(
					je_amount,
					"salary (bank transfer)",
					cheque_no=self.bank_entry_reference_no,
				)
			finally:
				self.employee_based_payroll_payable_entries = original_employee_entries

		for payment in cheque_payments:
			self.create_cheque_bank_entry(
				amount=payment["amount"],
				cheque_no=payment["payment_reference_no"],
				user_remark=_("Cheque payment for {0}").format(payment["salary_slip"]),
			)

		self.submitted_bank = 1
		self.db_update()

	def get_salary_slip_payment_map(self) -> dict:
		"""employee -> slip payment fields for bank/cheque split."""
		slips = frappe.get_all(
			"Salary Slip",
			filters={"payroll_entry": self.name, "docstatus": 1},
			fields=["name", "employee", "net_pay", "mode_of_payment", "payment_reference_no"],
		)
		return {s.employee: s for s in slips}

	def validate_slips_ready_for_bank_entry(self, slip_map):
		missing_mop = []
		missing_cheque_ref = []
		for slip in slip_map.values():
			if not slip.mode_of_payment:
				missing_mop.append(slip.name)
			elif self.is_cheque_mode(slip.mode_of_payment) and not slip.payment_reference_no:
				missing_cheque_ref.append(slip.name)

		if missing_mop:
			frappe.throw(
				_("Set Mode of Payment on all Salary Slips before creating Bank Entries. Missing: {0}").format(
					comma_and(missing_mop[:10])
				)
			)
		if missing_cheque_ref:
			frappe.throw(
				_("Set Payment Reference No on cheque Salary Slips before creating Bank Entries. Missing: {0}").format(
					comma_and(missing_cheque_ref[:10])
				)
			)

	def create_cheque_bank_entry(self, amount, cheque_no, user_remark):
		"""One Bank Entry per cheque: Dr Payroll Payable / Cr Payment Account, no employee party."""
		if flt(amount) <= 0:
			return

		payroll_payable_account = self.payroll_payable_account
		precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")
		accounts = []
		currencies = []
		company_currency = erpnext.get_company_currency(self.company)
		accounting_dimensions = get_accounting_dimensions() or []

		exchange_rate, je_amount = self.get_amount_and_exchange_rate_for_journal_entry(
			self.payment_account, amount, company_currency, currencies
		)
		accounts.append(
			self.update_accounting_dimensions(
				{
					"account": self.payment_account,
					"bank_account": self.bank_account,
					"credit_in_account_currency": flt(je_amount, precision),
					"exchange_rate": flt(exchange_rate),
					"cost_center": self.cost_center,
				},
				accounting_dimensions,
			)
		)

		exchange_rate, je_amount = self.get_amount_and_exchange_rate_for_journal_entry(
			payroll_payable_account, amount, company_currency, currencies
		)
		accounts.append(
			self.update_accounting_dimensions(
				{
					"account": payroll_payable_account,
					"debit_in_account_currency": flt(je_amount, precision),
					"exchange_rate": flt(exchange_rate),
					"reference_type": self.doctype,
					"reference_name": self.name,
					"cost_center": self.cost_center,
				},
				accounting_dimensions,
			)
		)

		self.make_journal_entry(
			accounts,
			currencies,
			voucher_type="Bank Entry",
			user_remark=user_remark,
			cheque_no=cheque_no,
			cheque_date=self.posting_date,
		)

	@frappe.whitelist()
	def email_slips(self):
		self.check_permission("write")
		salary_slips = self.get_sal_slip_list(ss_status=1, as_dict=True)
		self.email_salary_slip(salary_slips)

	def validate_ready_for_journal_entries(self):
		if self.status != "Completed":
			frappe.throw(_("Payroll Entry must be Completed before creating Journal Entries"))
		draft_count = frappe.db.count("Salary Slip", {"payroll_entry": self.name, "docstatus": 0})
		if draft_count:
			frappe.throw(
				_("Cannot create Journal Entries while there are draft Salary Slips. Submit or cancel them first.")
			)
		if not cint(self.payslips_reviewed) and not self.are_all_payslips_reviewed():
			frappe.throw(_("All Salary Slips must be submitted before creating Journal Entries"))

	def are_all_payslips_reviewed(self) -> bool:
		"""Submitted salary slips are treated as reviewed. Drafts block readiness."""
		if frappe.db.count("Salary Slip", {"payroll_entry": self.name, "docstatus": 0}):
			return False

		slips = frappe.get_all(
			"Salary Slip",
			filters={"payroll_entry": self.name, "docstatus": 1},
			fields=["name", "payroll_reviewed"],
		)
		if not slips:
			return False
		return all(cint(s.payroll_reviewed) for s in slips)

	def refresh_payslips_reviewed_flag(self):
		reviewed = self.are_all_payslips_reviewed()
		self.db_set("payslips_reviewed", cint(reviewed))
		self.payslips_reviewed = cint(reviewed)
		return reviewed

	def mark_submitted_slips_reviewed(self):
		"""Submitted = reviewed. Keep cancelled/draft slips unreviewed.

		Amended drafts keep their restored review flag so Cancel → Amend → resubmit
		does not drop them back to Not reviewed if the Payroll Entry is opened first.
		"""
		frappe.db.sql(
			"""
			UPDATE `tabSalary Slip`
			SET payroll_reviewed = 1
			WHERE payroll_entry = %s AND docstatus = 1 AND IFNULL(payroll_reviewed, 0) = 0
			""",
			self.name,
		)
		frappe.db.sql(
			"""
			UPDATE `tabSalary Slip`
			SET payroll_reviewed = 0
			WHERE payroll_entry = %s
				AND docstatus != 1
				AND IFNULL(payroll_reviewed, 0) = 1
				AND NOT (docstatus = 0 AND IFNULL(amended_from, '') != '')
			""",
			self.name,
		)

	def reopen_if_payslips_incomplete(self):
		"""If a completed PE has draft/cancelled gaps and bank JE is not posted, reopen it."""
		if self.status != "Completed" or cint(self.submitted_bank):
			return False

		if self.are_all_payslips_reviewed():
			return False

		self.db_set(
			{
				"status": "Submitted",
				"salary_slips_submitted": 0,
				"payslips_reviewed": 0,
			}
		)
		self.status = "Submitted"
		self.salary_slips_submitted = 0
		self.payslips_reviewed = 0
		return True

	@frappe.whitelist()
	def mark_complete(self):
		self.check_permission("write")
		if self.docstatus != 1:
			frappe.throw(_("Payroll Entry must be submitted before Completing"))
		if self.status == "Completed":
			frappe.msgprint(_("Payroll Entry is already Completed"), indicator="blue")
			return

		draft_count = frappe.db.count("Salary Slip", {"payroll_entry": self.name, "docstatus": 0})
		submitted_count = frappe.db.count("Salary Slip", {"payroll_entry": self.name, "docstatus": 1})
		if draft_count:
			frappe.throw(
				_(
					"Cannot Complete. There are {0} draft Salary Slip(s). Submit or cancel all drafts first."
				).format(draft_count)
			)
		if not submitted_count:
			frappe.throw(_("Cannot Complete. No submitted Salary Slips found for this Payroll Entry."))

		if not self.payment_account and self.cheque_payment_account:
			self.db_set("payment_account", self.cheque_payment_account)
			self.payment_account = self.cheque_payment_account

		if not self.payment_account:
			frappe.throw(_("Payment Account is mandatory before Completing Payroll Entry"))

		self.mark_submitted_slips_reviewed()
		self.db_set({"status": "Completed", "salary_slips_submitted": 1, "error_message": ""})
		self.status = "Completed"
		self.sync_default_mode_of_payment(overwrite=False)
		self.refresh_payslips_reviewed_flag()
		frappe.msgprint(_("Payroll Entry marked as Completed"), indicator="green")

	def get_modes_of_payment_for_payment_account(self, payment_account=None):
		"""Mode of Payment names linked to the Payroll Entry payment account (Doctors Pay pattern)."""
		payment_account = payment_account or self.payment_account
		if not payment_account or not self.company:
			return []
		return (
			frappe.get_all(
				"Mode of Payment Account",
				filters={"default_account": payment_account, "company": self.company},
				pluck="parent",
				order_by="parent asc",
			)
			or []
		)

	@frappe.whitelist()
	def get_modes_of_payment(self):
		self.check_permission("read")
		return {"modes_of_payment": self.get_modes_of_payment_for_payment_account()}

	def resolve_mode_of_payment(self, mode_of_payment, payment_account=None):
		payment_account = payment_account or self.payment_account
		valid_modes = self.get_modes_of_payment_for_payment_account(payment_account)
		if not valid_modes:
			frappe.throw(
				_("No Mode of Payment found for Payment Account {0} in company {1}").format(
					payment_account, self.company
				)
			)
		mode_of_payment = (mode_of_payment or "").strip()
		if not mode_of_payment:
			frappe.throw(_("Mode of Payment is required"))
		if mode_of_payment not in set(valid_modes):
			frappe.throw(
				_("Mode of Payment {0} is not configured for Payment Account {1}").format(
					mode_of_payment, payment_account
				)
			)
		return mode_of_payment

	def sync_default_mode_of_payment(self, overwrite=False):
		"""If exactly one MoP is linked to the payment account, set it on slips missing one."""
		modes = self.get_modes_of_payment_for_payment_account()
		if len(modes) != 1:
			return
		default_mode = modes[0]
		slips = frappe.get_all(
			"Salary Slip",
			filters={"payroll_entry": self.name, "docstatus": 1},
			fields=["name", "mode_of_payment"],
		)
		for slip in slips:
			if overwrite or not slip.mode_of_payment:
				frappe.db.set_value("Salary Slip", slip.name, "mode_of_payment", default_mode)

	def clear_invalid_slip_modes_of_payment(self):
		"""Clear slip MoPs that are no longer valid for the current PE payment account."""
		valid_modes = set(self.get_modes_of_payment_for_payment_account())
		slips = frappe.get_all(
			"Salary Slip",
			filters={"payroll_entry": self.name, "docstatus": 1},
			fields=["name", "mode_of_payment"],
		)
		for slip in slips:
			if slip.mode_of_payment and slip.mode_of_payment not in valid_modes:
				frappe.db.set_value("Salary Slip", slip.name, "mode_of_payment", None)

	@frappe.whitelist()
	def get_payslips_for_review(self):
		self.check_permission("read")
		self.mark_submitted_slips_reviewed()
		self.refresh_payslips_reviewed_flag()

		slips = frappe.get_all(
			"Salary Slip",
			filters={"payroll_entry": self.name},
			fields=[
				"name",
				"employee",
				"employee_name",
				"net_pay",
				"docstatus",
				"payroll_reviewed",
				"journal_entry",
				"currency",
				"mode_of_payment",
				"payment_reference_no",
			],
			order_by="docstatus asc, employee asc",
		)
		draft_count = 0
		modes_of_payment = list(self.get_modes_of_payment_for_payment_account())
		seen_modes = set(modes_of_payment)
		for slip in slips:
			if cint(slip.docstatus) == 0:
				draft_count += 1
			# Include MoPs already set on slips so filters remain usable
			if slip.mode_of_payment and slip.mode_of_payment not in seen_modes:
				modes_of_payment.append(slip.mode_of_payment)
				seen_modes.add(slip.mode_of_payment)
			slip.is_cheque = cint(self.is_cheque_mode(slip.mode_of_payment))

		return {
			"payslips": slips,
			"payment_account": self.payment_account,
			"cheque_payment_account": self.cheque_payment_account,
			"bank_entry_reference_no": self.bank_entry_reference_no,
			"modes_of_payment": modes_of_payment,
			"payslips_reviewed": cint(self.payslips_reviewed),
			"draft_count": draft_count,
			"status": self.status,
			"can_edit_mode_of_payment": cint(self.docstatus == 1 and not cint(self.submitted_bank)),
			"submitted_je": cint(
				frappe.db.count(
					"Journal Entry Account", {"reference_name": self.name, "docstatus": 1}
				)
				> 0
			),
			"submitted_bank": cint(self.submitted_bank),
		}

	def validate_payment_editable(self):
		if self.docstatus != 1:
			frappe.throw(_("Payment details can only be changed after Payroll Entry is submitted"))
		if cint(self.submitted_bank):
			frappe.throw(_("Cannot change payment details after Bank Entry has been created"))

	@frappe.whitelist()
	def set_payment_account(self, payment_account=None, use_cheque=0):
		"""Change the single Payroll Entry payment account (shared by all slips)."""
		self.check_permission("write")
		self.validate_payment_editable()

		use_cheque = cint(use_cheque)
		if use_cheque:
			if not self.cheque_payment_account:
				frappe.throw(_("Cheque Payment Account is not set"))
			payment_account = self.cheque_payment_account

		if not payment_account:
			frappe.throw(_("Payment Account is required"))

		self.db_set("payment_account", payment_account)
		self.payment_account = payment_account
		self.clear_invalid_slip_modes_of_payment()
		self.sync_default_mode_of_payment(overwrite=False)
		return payment_account

	@frappe.whitelist()
	def set_salary_slip_mode_of_payment(self, salary_slip, mode_of_payment):
		self.check_permission("write")
		self.validate_payment_editable()
		if not self.payment_account:
			frappe.throw(_("Set Payment Account on Payroll Entry before assigning Mode of Payment"))

		slip = frappe.get_doc("Salary Slip", salary_slip)
		if slip.payroll_entry != self.name:
			frappe.throw(_("Salary Slip {0} does not belong to this Payroll Entry").format(salary_slip))
		if slip.docstatus != 1:
			frappe.throw(_("Only submitted Salary Slips can be updated"))

		mode_of_payment = self.resolve_mode_of_payment(mode_of_payment)
		frappe.db.set_value("Salary Slip", salary_slip, "mode_of_payment", mode_of_payment)
		return {"salary_slip": salary_slip, "mode_of_payment": mode_of_payment}

	@frappe.whitelist()
	def set_all_salary_slip_mode_of_payment(self, mode_of_payment):
		self.check_permission("write")
		self.validate_payment_editable()
		if not self.payment_account:
			frappe.throw(_("Set Payment Account on Payroll Entry before assigning Mode of Payment"))

		mode_of_payment = self.resolve_mode_of_payment(mode_of_payment)
		slips = frappe.get_all(
			"Salary Slip",
			filters={"payroll_entry": self.name, "docstatus": 1},
			pluck="name",
		)
		for name in slips:
			frappe.db.set_value("Salary Slip", name, "mode_of_payment", mode_of_payment)
		return {"mode_of_payment": mode_of_payment, "count": len(slips)}

	@frappe.whitelist()
	def set_bank_entry_reference_no(self, bank_entry_reference_no=None):
		self.check_permission("write")
		self.validate_payment_editable()
		bank_entry_reference_no = (bank_entry_reference_no or "").strip() or None
		self.db_set("bank_entry_reference_no", bank_entry_reference_no)
		self.bank_entry_reference_no = bank_entry_reference_no
		return {"bank_entry_reference_no": bank_entry_reference_no}

	@frappe.whitelist()
	def set_salary_slip_payment_reference_no(self, salary_slip, payment_reference_no=None):
		self.check_permission("write")
		self.validate_payment_editable()

		slip = frappe.get_doc("Salary Slip", salary_slip)
		if slip.payroll_entry != self.name:
			frappe.throw(_("Salary Slip {0} does not belong to this Payroll Entry").format(salary_slip))
		if slip.docstatus != 1:
			frappe.throw(_("Only submitted Salary Slips can be updated"))

		payment_reference_no = (payment_reference_no or "").strip() or None
		frappe.db.set_value("Salary Slip", salary_slip, "payment_reference_no", payment_reference_no)
		return {"salary_slip": salary_slip, "payment_reference_no": payment_reference_no}

	@frappe.whitelist()
	def bulk_create_journal_entries(self):
		self.check_permission("write")
		self.validate_ready_for_journal_entries()
		if not self.payment_account:
			frappe.throw(_("Payment Account is mandatory to create Journal Entries"))

		salary_slips = self.get_sal_slip_list(ss_status=1, as_dict=True)
		has_accrual_je = (
			frappe.db.count("Journal Entry Account", {"reference_name": self.name, "docstatus": 1}) > 0
		)

		if not has_accrual_je and salary_slips:
			if len(salary_slips) > 30 or frappe.flags.enqueue_payroll_entry:
				self.db_set("status", "Queued")
				frappe.enqueue(
					create_payroll_journal_entries_in_background,
					timeout=3000,
					payroll_entry_name=self.name,
					create_bank=True,
				)
				frappe.msgprint(
					_("Journal Entry creation is queued. It may take a few minutes"),
					alert=True,
					indicator="blue",
				)
				return {"queued": 1}

			self.make_accrual_jv_entry(salary_slips)

		if not cint(self.submitted_bank):
			self.reload()
			frappe.flags.skip_payroll_je_gate = True
			try:
				self.make_bank_entry()
			finally:
				frappe.flags.skip_payroll_je_gate = False

		self.db_set("status", "Completed")
		self.status = "Completed"
		frappe.msgprint(_("Accrual and payment Journal Entries created"), indicator="green")
		return {"queued": 0}

	@frappe.whitelist()
	def submit_journal_entry(self):
		self.check_permission("write")
		self.validate_ready_for_journal_entries()
		salary_slips = self.get_sal_slip_list(ss_status=1, as_dict=True)

		if len(salary_slips) > 30 or frappe.flags.enqueue_payroll_entry:
			self.db_set("status", "Queued")
			frappe.enqueue(
				self.make_accrual_jv_entry,
				timeout=3000,
				payroll_entry=self,
				salary_slips=salary_slips,
				publish_progress=False,
			)
			frappe.msgprint(
				_("Journal Entry is queued. It may take a few minutes"),
				alert=True,
				indicator="blue",
			)
		else:
			self.make_accrual_jv_entry(salary_slips)
			self.db_set("status", "Completed")

	@frappe.whitelist()
	def submit_mra(self):
		self.check_permission("write")

		salary_slips = self.get_salary_slip_details()
		accounting_dimensions = get_accounting_dimensions() or []
		currencies = []
		company_currency = erpnext.get_company_currency(self.company)
		precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")

		mra_accounts = ['NSF', 'Levy', 'CSG', 'PRGF', 'Paye']
		accounts = []
		components = {}

		company_abbr = frappe.db.get_value(
			"Company", self.company, "abbr", cache=True
		)

		for ss in salary_slips:
			if any(mra_account in ss.salary_component for mra_account in mra_accounts):
				skey = ss.salary_component.split(" ")[0]
				components[skey] = components.get(skey, 0) + ss.amount
		
		for component, c_amount in components.items():
			exchange_rate, amount = self.get_amount_and_exchange_rate_for_journal_entry(
				self.payment_account, c_amount, company_currency, currencies
			)				
			accounts.append(
				self.update_accounting_dimensions(
					{
						"account": self.payment_account,
						"bank_account": self.bank_account,
						"credit_in_account_currency": flt(amount, precision),
						"exchange_rate": flt(exchange_rate),
						"cost_center": self.cost_center,
						"reference_type": self.doctype,
						"reference_name": self.name,
					},
					accounting_dimensions,
				)
			)
			accounts.append(
				self.update_accounting_dimensions(
					{
						"account": f'Accrued - {component.upper()} - {company_abbr}',
						"debit_in_account_currency": flt(amount, precision),
						"exchange_rate": flt(exchange_rate),
						"cost_center": self.cost_center,
						"reference_type": self.doctype,
						"reference_name": self.name,
					},
					accounting_dimensions,
				)
			)

		self.make_journal_entry(
			accounts,
			currencies,
			voucher_type="Bank Entry",
			user_remark=_("Payment of {0} from {1} to {2}").format(
				"MRA Submission", self.start_date, self.end_date
			),
		)

		self.submitted_mra = 1
		self.db_update()

	def get_salary_slip_details(self):
		SalarySlip = frappe.qb.DocType("Salary Slip")
		SalaryDetail = frappe.qb.DocType("Salary Detail")

		return (
			frappe.qb.from_(SalarySlip)
			.join(SalaryDetail)
			.on(SalarySlip.name == SalaryDetail.parent)
			.select(
				SalarySlip.name,
				SalarySlip.employee,
				SalarySlip.salary_structure,
				SalaryDetail.salary_component,
				SalaryDetail.amount,
				SalaryDetail.parentfield,
			)
			.where(
				(SalarySlip.docstatus == 1)
				& (SalarySlip.start_date >= self.start_date)
				& (SalarySlip.end_date <= self.end_date)
				& (SalarySlip.payroll_entry == self.name)
			)
		).run(as_dict=True)

	def set_accounting_entries_for_bank_entry(self, je_payment_amount, user_remark, cheque_no=None):
		payroll_payable_account = self.payroll_payable_account
		precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency")

		accounts = []
		currencies = []
		company_currency = erpnext.get_company_currency(self.company)
		accounting_dimensions = get_accounting_dimensions() or []

		exchange_rate, amount = self.get_amount_and_exchange_rate_for_journal_entry(
			self.payment_account, je_payment_amount, company_currency, currencies
		)
		accounts.append(
			self.update_accounting_dimensions(
				{
					"account": self.payment_account,
					"bank_account": self.bank_account,
					"credit_in_account_currency": flt(amount, precision),
					"exchange_rate": flt(exchange_rate),
					"cost_center": self.cost_center,
				},
				accounting_dimensions,
			)
		)

		if self.employee_based_payroll_payable_entries:
			for employee, employee_details in self.employee_based_payroll_payable_entries.items():
				je_payment_amount = employee_details.get("earnings", 0) - (
					employee_details.get("deductions", 0)
				)
				exchange_rate, amount = self.get_amount_and_exchange_rate_for_journal_entry(
					self.payment_account, je_payment_amount, company_currency, currencies
				)

				cost_centers = self.get_payroll_cost_centers_for_employee(
					employee, employee_details.get("salary_structure")
				)

				for cost_center, percentage in cost_centers.items():
					amount_against_cost_center = flt(amount) * percentage / 100
					accounts.append(
						self.update_accounting_dimensions(
							{
								"account": payroll_payable_account,
								"debit_in_account_currency": flt(amount_against_cost_center, precision),
								"exchange_rate": flt(exchange_rate),
								"reference_type": self.doctype,
								"reference_name": self.name,
								"party_type": "Employee",
								"party": employee,
								"cost_center": cost_center,
							},
							accounting_dimensions,
						)
					)
		else:
			exchange_rate, amount = self.get_amount_and_exchange_rate_for_journal_entry(
				payroll_payable_account, je_payment_amount, company_currency, currencies
			)
			accounts.append(
				self.update_accounting_dimensions(
					{
						"account": payroll_payable_account,
						"debit_in_account_currency": flt(amount, precision),
						"exchange_rate": flt(exchange_rate),
						"reference_type": self.doctype,
						"reference_name": self.name,
						"cost_center": self.cost_center,
					},
					accounting_dimensions,
				)
			)

		self.make_journal_entry(
			accounts,
			currencies,
			voucher_type="Bank Entry",
			user_remark=_("Payment of {0} from {1} to {2}").format(
				user_remark, self.start_date, self.end_date
			),
			cheque_no=cheque_no,
			cheque_date=self.posting_date if cheque_no else None,
		)

	def update_salary_slip_status(self, submitted_salary_slips, jv_name=None):
		SalarySlip = frappe.qb.DocType("Salary Slip")
		(
			frappe.qb.update(SalarySlip)
			.set(SalarySlip.journal_entry, jv_name)
			.where(SalarySlip.name.isin([salary_slip.name for salary_slip in submitted_salary_slips]))
		).run()

	def set_start_end_dates(self):
		self.update(
			get_start_end_dates(self.payroll_frequency, self.start_date or self.posting_date, self.company)
		)

	@frappe.whitelist()
	def get_employees_with_unmarked_attendance(self) -> list[dict] | None:
		if not self.validate_attendance:
			return

		unmarked_attendance = []
		employee_details = self.get_employee_and_attendance_details()
		default_holiday_list = frappe.db.get_value(
			"Company", self.company, "default_holiday_list", cache=True
		)

		for emp in self.employees:
			details = next((record for record in employee_details if record.name == emp.employee), None)
			if not details:
				continue

			start_date, end_date = self.get_payroll_dates_for_employee(details)
			holidays = self.get_holidays_count(
				details.holiday_list or default_holiday_list, start_date, end_date
			)
			payroll_days = date_diff(end_date, start_date) + 1
			unmarked_days = payroll_days - (holidays + details.attendance_count)

			if unmarked_days > 0:
				unmarked_attendance.append(
					{
						"employee": emp.employee,
						"employee_name": emp.employee_name,
						"unmarked_days": unmarked_days,
					}
				)

		return unmarked_attendance

	def get_employee_and_attendance_details(self) -> list[dict]:
		"""Returns a list of employee and attendance details like
		[
		        {
		                "name": "HREMP00001",
		                "date_of_joining": "2019-01-01",
		                "relieving_date": "2022-01-01",
		                "holiday_list": "Holiday List Company",
		                "attendance_count": 22
		        }
		]
		"""
		employees = [emp.employee for emp in self.employees]

		Employee = frappe.qb.DocType("Employee")
		Attendance = frappe.qb.DocType("Attendance")

		return (
			frappe.qb.from_(Employee)
			.left_join(Attendance)
			.on(
				(Employee.name == Attendance.employee)
				& (Attendance.attendance_date.between(self.start_date, self.end_date))
				& (Attendance.docstatus == 1)
			)
			.select(
				Employee.name,
				Employee.date_of_joining,
				Employee.relieving_date,
				Employee.holiday_list,
				Count(Attendance.name).as_("attendance_count"),
			)
			.where(Employee.name.isin(employees))
			.groupby(Employee.name)
		).run(as_dict=True)

	def get_payroll_dates_for_employee(self, employee_details: dict) -> tuple[str, str]:
		start_date = self.start_date
		if employee_details.date_of_joining > getdate(self.start_date):
			start_date = employee_details.date_of_joining

		end_date = self.end_date
		if employee_details.relieving_date and employee_details.relieving_date < getdate(self.end_date):
			end_date = employee_details.relieving_date

		return start_date, end_date

	def get_holidays_count(self, holiday_list: str, start_date: str, end_date: str) -> float:
		"""Returns number of holidays between start and end dates in the holiday list"""
		if not hasattr(self, "_holidays_between_dates"):
			self._holidays_between_dates = {}

		key = f"{start_date}-{end_date}-{holiday_list}"
		if key in self._holidays_between_dates:
			return self._holidays_between_dates[key]

		holidays = frappe.db.get_all(
			"Holiday",
			filters={"parent": holiday_list, "holiday_date": ("between", [start_date, end_date])},
			fields=["COUNT(*) as holidays_count"],
		)[0]

		if holidays:
			self._holidays_between_dates[key] = holidays.holidays_count

		return self._holidays_between_dates.get(key) or 0

	@frappe.whitelist()
	def get_missing_salary_slips_report(self):
		"""Debug method to identify employees without salary slips"""
		self.check_permission("read")
		
		# Get all employees in the payroll entry
		payroll_employees = {emp.employee: emp.employee_name for emp in self.employees}
		
		# Get employees who have submitted salary slips
		submitted_slips = frappe.db.sql("""
			SELECT DISTINCT employee, name
			FROM `tabSalary Slip`
			WHERE payroll_entry = %s 
			AND docstatus = 1
		""", self.name, as_dict=True)
		
		employees_with_slips = {slip.employee: slip.name for slip in submitted_slips}
		
		# Get all slips (including cancelled/draft)
		all_slips = frappe.db.sql("""
			SELECT employee, name, docstatus,
				   CASE docstatus 
					   WHEN 0 THEN 'Draft'
					   WHEN 1 THEN 'Submitted'
					   WHEN 2 THEN 'Cancelled'
				   END as status,
				   amended_from
			FROM `tabSalary Slip`
			WHERE payroll_entry = %s 
			ORDER BY employee, docstatus
		""", self.name, as_dict=True)
		
		# Build report
		report = {
			"payroll_entry": self.name,
			"period": f"{self.start_date} to {self.end_date}",
			"total_employees": len(payroll_employees),
			"employees_with_submitted_slips": len(employees_with_slips),
			"missing_employees": [],
			"all_slips_status": []
		}
		
		# Find missing employees
		for emp_id, emp_name in payroll_employees.items():
			if emp_id not in employees_with_slips:
				report["missing_employees"].append({
					"employee": emp_id,
					"employee_name": emp_name
				})
		
		# Group slips by employee
		from collections import defaultdict
		slips_by_employee = defaultdict(list)
		for slip in all_slips:
			slips_by_employee[slip.employee].append({
				"slip_name": slip.name,
				"status": slip.status,
				"docstatus": slip.docstatus,
				"amended_from": slip.amended_from
			})
		
		report["all_slips_status"] = dict(slips_by_employee)
		
		return report


def get_salary_structure(
	company: str, currency: str, salary_slip_based_on_timesheet: int, payroll_frequency: str
) -> list[str]:
	SalaryStructure = frappe.qb.DocType("Salary Structure")

	query = (
		frappe.qb.from_(SalaryStructure)
		.select(SalaryStructure.name)
		.where(
			(SalaryStructure.docstatus == 1)
			& (SalaryStructure.is_active == "Yes")
			& (SalaryStructure.company == company)
			& (SalaryStructure.currency == currency)
			& (SalaryStructure.salary_slip_based_on_timesheet == salary_slip_based_on_timesheet)
		)
	)

	if not salary_slip_based_on_timesheet:
		query = query.where(SalaryStructure.payroll_frequency == payroll_frequency)

	return query.run(pluck=True)


def get_filtered_employees(
	sal_struct,
	filters,
	searchfield=None,
	search_string=None,
	fields=None,
	as_dict=False,
	limit=None,
	offset=None,
	ignore_match_conditions=False,
) -> list:
	SalaryStructureAssignment = frappe.qb.DocType("Salary Structure Assignment")
	Employee = frappe.qb.DocType("Employee")

	query = (
		frappe.qb.from_(Employee)
		.join(SalaryStructureAssignment)
		.on(Employee.name == SalaryStructureAssignment.employee)
		.where(
			(SalaryStructureAssignment.docstatus == 1)
			& (Employee.status != "Inactive")
			& (Employee.company == filters.company)
			& ((Employee.date_of_joining <= filters.end_date) | (Employee.date_of_joining.isnull()))
			& ((Employee.relieving_date >= filters.end_date) | (Employee.relieving_date.isnull()))
			& (SalaryStructureAssignment.salary_structure.isin(sal_struct))
			& (SalaryStructureAssignment.payroll_payable_account == filters.payroll_payable_account)
			& (filters.end_date >= SalaryStructureAssignment.from_date)
		)
	)

	query = set_fields_to_select(query, fields)
	query = set_searchfield(query, searchfield, search_string, qb_object=Employee)
	query = set_filter_conditions(query, filters, qb_object=Employee)

	if not ignore_match_conditions:
		query = set_match_conditions(query=query, qb_object=Employee)

	if limit:
		query = query.limit(limit)

	if offset:
		query = query.offset(offset)

	return query.run(as_dict=as_dict)


def set_fields_to_select(query, fields: list[str] | None = None):
	default_fields = ["employee", "employee_name", "department", "designation"]

	if fields:
		query = query.select(*fields).distinct()
	else:
		query = query.select(*default_fields).distinct()

	return query


def set_searchfield(query, searchfield, search_string, qb_object):
	if searchfield:
		query = query.where(
			(qb_object[searchfield].like("%" + search_string + "%"))
			| (qb_object.employee_name.like("%" + search_string + "%"))
		)

	return query


def set_filter_conditions(query, filters, qb_object):
	"""Append optional filters to employee query"""
	if filters.get("employees"):
		query = query.where(qb_object.name.notin(filters.get("employees")))

	for fltr_key in ["branch", "department", "designation", "grade"]:
		if filters.get(fltr_key):
			query = query.where(qb_object[fltr_key] == filters[fltr_key])

	return query


def set_match_conditions(query, qb_object):
	match_conditions = get_match_cond("Employee", as_condition=False)

	for cond in match_conditions:
		if isinstance(cond, dict):
			for key, value in cond.items():
				if isinstance(value, list):
					query = query.where(qb_object[key].isin(value))
				else:
					query = query.where(qb_object[key] == value)

	return query


def remove_payrolled_employees(emp_list, start_date, end_date):
	SalarySlip = frappe.qb.DocType("Salary Slip")

	employees_with_payroll = (
		frappe.qb.from_(SalarySlip)
		.select(SalarySlip.employee)
		.where(
			(SalarySlip.docstatus == 1)
			& (SalarySlip.start_date == start_date)
			& (SalarySlip.end_date == end_date)
		)
	).run(pluck=True)

	return [emp_list[emp] for emp in emp_list if emp not in employees_with_payroll]


@frappe.whitelist()
def get_start_end_dates(payroll_frequency, start_date=None, company=None):
	"""Returns dict of start and end dates for given payroll frequency based on start_date"""

	if payroll_frequency == "Monthly" or payroll_frequency == "Bimonthly" or payroll_frequency == "":
		fiscal_year = get_fiscal_year(start_date, company=company)[0]
		month = "%02d" % getdate(start_date).month
		m = get_month_details(fiscal_year, month)
		if payroll_frequency == "Bimonthly":
			if getdate(start_date).day <= 15:
				start_date = m["month_start_date"]
				end_date = m["month_mid_end_date"]
			else:
				start_date = m["month_mid_start_date"]
				end_date = m["month_end_date"]
		else:
			start_date = m["month_start_date"]
			end_date = m["month_end_date"]

	if payroll_frequency == "Weekly":
		end_date = add_days(start_date, 6)

	if payroll_frequency == "Fortnightly":
		end_date = add_days(start_date, 13)

	if payroll_frequency == "Daily":
		end_date = start_date

	return frappe._dict({"start_date": start_date, "end_date": end_date})


def get_frequency_kwargs(frequency_name):
	frequency_dict = {
		"monthly": {"months": 1},
		"fortnightly": {"days": 14},
		"weekly": {"days": 7},
		"daily": {"days": 1},
	}
	return frequency_dict.get(frequency_name)


@frappe.whitelist()
def get_end_date(start_date, frequency):
	start_date = getdate(start_date)
	frequency = frequency.lower() if frequency else "monthly"
	kwargs = get_frequency_kwargs(frequency) if frequency != "bimonthly" else get_frequency_kwargs("monthly")

	# weekly, fortnightly and daily intervals have fixed days so no problems
	end_date = add_to_date(start_date, **kwargs) - relativedelta(days=1)
	if frequency != "bimonthly":
		return dict(end_date=end_date.strftime(DATE_FORMAT))

	else:
		return dict(end_date="")


def get_month_details(year, month):
	ysd = frappe.db.get_value("Fiscal Year", year, "year_start_date")
	if ysd:
		import calendar
		import datetime

		diff_mnt = cint(month) - cint(ysd.month)
		if diff_mnt < 0:
			diff_mnt = 12 - int(ysd.month) + cint(month)
		msd = ysd + relativedelta(months=diff_mnt)  # month start date
		month_days = cint(calendar.monthrange(cint(msd.year), cint(month))[1])  # days in month
		mid_start = datetime.date(msd.year, cint(month), 16)  # month mid start date
		mid_end = datetime.date(msd.year, cint(month), 15)  # month mid end date
		med = datetime.date(msd.year, cint(month), month_days)  # month end date
		return frappe._dict(
			{
				"year": msd.year,
				"month_start_date": msd,
				"month_end_date": med,
				"month_mid_start_date": mid_start,
				"month_mid_end_date": mid_end,
				"month_days": month_days,
			}
		)
	else:
		frappe.throw(_("Fiscal Year {0} not found").format(year))


def get_payroll_entry_bank_entries(payroll_entry_name):
	je = frappe.qb.DocType("Journal Entry")
	jea = frappe.qb.DocType("Journal Entry Account")

	journal_entries = (
		frappe.qb.from_(je)
		.from_(jea)
		.select(je.name)
		.where(
			(je.name == jea.parent)
			& (je.voucher_type == "Bank Entry")
			& (jea.reference_name == payroll_entry_name)
			& (jea.reference_type == "Payroll Entry")
		)
	).run(as_dict=True)

	return journal_entries


@frappe.whitelist()
def payroll_entry_has_bank_entries(name: str):
	response = {}
	bank_entries = get_payroll_entry_bank_entries(name)
	response["submitted"] = 1 if bank_entries else 0

	return response


def log_payroll_failure(process, payroll_entry, error):
	error_log = frappe.log_error(
		title=_("Salary Slip {0} failed for Payroll Entry {1}").format(process, payroll_entry.name)
	)
	message_log = frappe.message_log.pop() if frappe.message_log else str(error)

	try:
		if isinstance(message_log, str):
			error_message = json.loads(message_log).get("message")
		else:
			error_message = message_log.get("message")
	except Exception:
		error_message = message_log

	error_message += "\n" + _("Check Error Log {0} for more details.").format(
		get_link_to_form("Error Log", error_log.name)
	)

	payroll_entry.db_set({"error_message": error_message, "status": "Failed"})


def create_salary_slips_for_employees(employees, args, publish_progress=True):
	payroll_entry = frappe.get_cached_doc("Payroll Entry", args.payroll_entry)

	try:
		salary_slips_exist_for = get_existing_salary_slips(employees, args)
		count = 0

		employees = list(set(employees) - set(salary_slips_exist_for))
		for emp in employees:
			args.update({"doctype": "Salary Slip", "employee": emp})
			frappe.get_doc(args).insert()

			count += 1
			if publish_progress:
				frappe.publish_progress(
					count * 100 / len(employees),
					title=_("Creating Salary Slips..."),
				)

		payroll_entry.db_set({"status": "Submitted", "salary_slips_created": 1, "error_message": ""})

		if salary_slips_exist_for:
			frappe.msgprint(
				_(
					"Salary Slips already exist for employees {}, and will not be processed by this payroll."
				).format(frappe.bold(", ".join(emp for emp in salary_slips_exist_for))),
				title=_("Message"),
				indicator="orange",
			)

	except Exception as e:
		frappe.db.rollback()
		log_payroll_failure("creation", payroll_entry, e)

	finally:
		frappe.db.commit()  # nosemgrep
		frappe.publish_realtime("completed_salary_slip_creation", user=frappe.session.user)


def show_payroll_submission_status(submitted, unsubmitted, payroll_entry):
	if not submitted and not unsubmitted:
		frappe.msgprint(
			_(
				"No salary slip found to submit for the above selected criteria OR salary slip already submitted"
			)
		)
	elif submitted and not unsubmitted:
		frappe.msgprint(
			_("Salary Slips submitted for period from {0} to {1}").format(
				payroll_entry.start_date, payroll_entry.end_date
			)
		)
	elif unsubmitted:
		frappe.msgprint(
			_("Could not submit some Salary Slips: {}").format(
				", ".join(get_link_to_form("Salary Slip", entry) for entry in unsubmitted)
			)
		)


def get_existing_salary_slips(employees, args):
	SalarySlip = frappe.qb.DocType("Salary Slip")

	return (
		frappe.qb.from_(SalarySlip)
		.select(SalarySlip.employee)
		.distinct()
		.where(
			(SalarySlip.docstatus != 2)
			& (SalarySlip.company == args.company)
			& (SalarySlip.payroll_entry == args.payroll_entry)
			& (SalarySlip.start_date >= args.start_date)
			& (SalarySlip.end_date <= args.end_date)
			& (SalarySlip.employee.isin(employees))
		)
	).run(pluck=True)


def submit_salary_slips_for_employees(payroll_entry, salary_slips, publish_progress=True):
	try:
		submitted = []
		unsubmitted = []
		frappe.flags.via_payroll_entry = True
		count = 0

		for entry in salary_slips:
			salary_slip = frappe.get_doc("Salary Slip", entry[0])
			if salary_slip.net_pay < 0:
				unsubmitted.append(entry[0])
			else:
				try:
					salary_slip.submit()
					submitted.append(salary_slip)
				except frappe.ValidationError:
					unsubmitted.append(entry[0])

			count += 1
			if publish_progress:
				frappe.publish_progress(
					count * 100 / len(salary_slips), title=_("Submitting Salary Slips...")
				)

		if submitted:
			payroll_entry.db_set({"salary_slips_submitted": 1, "status": "Submitted", "error_message": ""})

		show_payroll_submission_status(submitted, unsubmitted, payroll_entry)

	except Exception as e:
		frappe.db.rollback()
		log_payroll_failure("submission", payroll_entry, e)

	finally:
		frappe.db.commit()  # nosemgrep
		frappe.publish_realtime("completed_salary_slip_submission", user=frappe.session.user)

	frappe.flags.via_payroll_entry = False


def create_payroll_journal_entries_in_background(payroll_entry_name, create_bank=True):
	payroll_entry = frappe.get_doc("Payroll Entry", payroll_entry_name)
	try:
		salary_slips = payroll_entry.get_sal_slip_list(ss_status=1, as_dict=True)
		has_accrual_je = (
			frappe.db.count("Journal Entry Account", {"reference_name": payroll_entry.name, "docstatus": 1})
			> 0
		)
		if not has_accrual_je and salary_slips:
			payroll_entry.make_accrual_jv_entry(salary_slips)

		if create_bank and not cint(payroll_entry.submitted_bank):
			payroll_entry.reload()
			frappe.flags.skip_payroll_je_gate = True
			try:
				payroll_entry.make_bank_entry()
			finally:
				frappe.flags.skip_payroll_je_gate = False

		payroll_entry.db_set({"status": "Completed", "error_message": ""})
	except Exception as e:
		frappe.db.rollback()
		log_payroll_failure("submission", payroll_entry, e)
	finally:
		frappe.db.commit()  # nosemgrep
		frappe.publish_realtime("completed_salary_slip_submission", user=frappe.session.user)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_payroll_entries_for_jv(doctype, txt, searchfield, start, page_len, filters):
	# nosemgrep: frappe-semgrep-rules.rules.frappe-using-db-sql
	return frappe.db.sql(
		f"""
		select name from `tabPayroll Entry`
		where `{searchfield}` LIKE %(txt)s
		and name not in
			(select reference_name from `tabJournal Entry Account`
				where reference_type="Payroll Entry")
		order by name limit %(start)s, %(page_len)s""",
		{"txt": "%%%s%%" % txt, "start": start, "page_len": page_len},
	)


def get_employee_list(
	filters: frappe._dict,
	searchfield=None,
	search_string=None,
	fields: list[str] | None = None,
	as_dict=True,
	limit=None,
	offset=None,
	ignore_match_conditions=False,
) -> list:
	sal_struct = get_salary_structure(
		filters.company,
		filters.currency,
		filters.salary_slip_based_on_timesheet,
		filters.payroll_frequency,
	)

	if not sal_struct:
		return []

	emp_list = get_filtered_employees(
		sal_struct,
		filters,
		searchfield,
		search_string,
		fields,
		as_dict=as_dict,
		limit=limit,
		offset=offset,
		ignore_match_conditions=ignore_match_conditions,
	)

	if as_dict:
		employees_to_check = {emp.employee: emp for emp in emp_list}
	else:
		employees_to_check = {emp[0]: emp for emp in emp_list}

	return remove_payrolled_employees(employees_to_check, filters.start_date, filters.end_date)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def employee_query(doctype, txt, searchfield, start, page_len, filters):
	filters = frappe._dict(filters)

	if not filters.payroll_frequency:
		frappe.throw(_("Select Payroll Frequency."))

	employee_list = get_employee_list(
		filters,
		searchfield=searchfield,
		search_string=txt,
		fields=["name", "employee_name"],
		as_dict=False,
		limit=page_len,
		offset=start,
	)

	return employee_list

