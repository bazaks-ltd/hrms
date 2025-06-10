# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

class EmployeeOvertime(Document):
	pass

	def validate(self):
			self.check_duplicate_overtime()
	
	def check_duplicate_overtime(self):
		# Check for existing overtime with same employee and time range
		existing = frappe.db.exists("Employee Overtime", {
			"employee": self.employee,
			"date": self.date,
			"from_time": self.from_time,
			"to_time": self.to_time,
			"name": ("!=", self.name)  # Exclude current document when updating
		})

		if existing:
			frappe.throw(_("Overtime record already exists for {0} on {1} from {2} to {3}").format(
				self.employee, self.date, self.from_time, self.to_time
		))
		print("No duplicate overtime found for employee:", self.employee)

@frappe.whitelist()
def get_overtime_approver(employee):
	emp_department = frappe.db.get_value("Employee", employee, ["department"])

	overtime_approver = frappe.db.get_value(
		"Department Approver",
		{"parent": emp_department, "parentfield": "overtime_approvers", "idx": 1},
		"approver",
	)
	return overtime_approver

