# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document
from frappe.utils import flt

class StatementofEmoluments(Document):
	def before_save(self):
		# recalculate totals on save
		self.recalculate_total()
        
	def recalculate_total(self):
		self.total_emoluments = (
				flt(self.salary_wages_basic) +
				flt(self.bonus_including_end_of_year) +
				flt(self.rent_or_housing_allowance) +
				flt(self.entertainment_allowance) +
				flt(self.transport_allowance) +
				flt(self.reimbursement_travelling_expenses) +
				flt(self.other_allowance) +
				flt(self.reimbursement_personal_expenses) +
				flt(self.reimbursement_passages) +
				flt(self.fringe_benefits) +
				flt(self.lump_sum_commutation) +
				flt(self.retirement_pension)
			)
		self.emoluments_net_of_exempt_income = self.total_emoluments - self.exempt_income

