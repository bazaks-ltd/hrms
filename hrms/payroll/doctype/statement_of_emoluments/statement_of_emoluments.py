# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate


class StatementofEmoluments(Document):
	def before_save(self):
		self.recalculate_total()

	def validate(self):
		self.validate_duplicate_for_year()

	def validate_duplicate_for_year(self):
		if not self.employee or not self.income_year:
			return

		filters = {
			"employee": self.employee,
			"income_year": cint(self.income_year),
			"docstatus": ("<", 2),
		}
		if not self.is_new():
			filters["name"] = ("!=", self.name)

		existing = frappe.db.get_value("Statement of Emoluments", filters, "name")
		if existing:
			link = frappe.utils.get_link_to_form("Statement of Emoluments", existing)
			frappe.throw(
				_("A Statement of Emoluments for this employee and year already exists: {0}").format(link),
				title=_("Duplicate Statement"),
			)

	def recalculate_total(self):
		self.total_emoluments = (
			flt(self.salary_wages_basic)
			+ flt(self.bonus_including_end_of_year)
			+ flt(self.rent_or_housing_allowance)
			+ flt(self.entertainment_allowance)
			+ flt(self.transport_allowance)
			+ flt(self.reimbursement_travelling_expenses)
			+ flt(self.other_allowance)
			+ flt(self.reimbursement_personal_expenses)
			+ flt(self.reimbursement_passages)
			+ flt(self.fringe_benefits)
			+ flt(self.lump_sum_commutation)
			+ flt(self.retirement_pension)
		)
		self.emoluments_net_of_exempt_income = flt(self.total_emoluments) - flt(self.exempt_income)

	def get_mauritius_fy_for_income_year(self):
		income_year = cint(self.income_year)
		if not income_year:
			frappe.throw(_("Please enter Income Year Ended"))
		period_end = date(income_year, 6, 30)
		period_start = date(income_year - 1, 7, 1)
		return period_start, period_end

	def apply_emoluments_values(self, values):
		for field, value in values.items():
			if field in ("period_start_date", "period_end_date"):
				continue
			if self.meta.has_field(field):
				# Keep user-selected signatory / declaration_date if already set
				if field == "signatory" and self.signatory:
					continue
				if field == "declaration_date" and self.declaration_date:
					continue
				self.set(field, value)

	@frappe.whitelist()
	def populate_from_employee(self, calculate_emoluments=True):
		"""Autofill employer/employee details and optionally calculate emoluments for the FY."""
		if not self.employee:
			frappe.throw(_("Please select an Employee"))

		employee = frappe.get_doc("Employee", self.employee)
		if not employee.company:
			frappe.throw(_("Employee {0} has no Company set").format(employee.name))

		company = frappe.get_doc("Company", employee.company)

		self.employee_full_name = employee.employee_name
		self.national_identity_card_no = employee.nid
		self.tax_account_no = employee.tan
		self.employed_from = employee.date_of_joining
		self.employer_full_name = company.registered_name
		self.paye_employer_registration_number = company.domain
		self.business_registration_number = company.brn

		if not self.income_year:
			# Default to current Mauritius FY end year from today
			today = getdate()
			self.income_year = today.year + 1 if today.month >= 7 else today.year

		period_start, period_end = self.get_mauritius_fy_for_income_year()
		self.employed_to = employee.relieving_date or period_end

		if not cint(calculate_emoluments):
			return self.as_dict()

		salary_slip = frappe.get_all(
			"Salary Slip",
			filters={
				"employee": self.employee,
				"docstatus": 1,
				"end_date": ["between", [period_start, period_end]],
			},
			order_by="end_date desc",
			limit=1,
		)
		if not salary_slip:
			frappe.throw(
				_(
					"No submitted Salary Slip found for {0} in income year {1} ({2} to {3})"
				).format(
					frappe.bold(self.employee),
					frappe.bold(self.income_year),
					period_start,
					period_end,
				)
			)

		slip_doc = frappe.get_doc("Salary Slip", salary_slip[0].name)
		values = slip_doc.get_emoluments_statement_values(
			period_start_date=period_start,
			period_end_date=period_end,
			declaration_date=self.declaration_date,
			signatory=self.signatory,
		)
		self.apply_emoluments_values(values)
		self.recalculate_total()
		return self.as_dict()
