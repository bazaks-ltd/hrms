# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EmployeeFollowup(Document):
	def validate(self):
		self.validate_followup_date()
		self.set_status()
	
	def validate_followup_date(self):
		if self.followup_date and self.employee:
			date_of_joining = frappe.db.get_value("Employee", self.employee, "date_of_joining")
			if date_of_joining and self.followup_date < date_of_joining:
				frappe.throw(_("Follow-up date cannot be before employee's date of joining"))
	
	def set_status(self):
		if self.followup_completed:
			self.status = "Completed"
		elif self.followup_date and self.followup_date < frappe.utils.today():
			if self.status == "Pending":
				self.status = "In Progress"
		elif not self.status:
			self.status = "Pending"
	
	def on_submit(self):
		self.set_status()
		if not self.followup_completed:
			frappe.msgprint(_("Please mark 'Follow-up Completed' before submitting"), alert=True)
	
	def on_update_after_submit(self):
		self.set_status()

