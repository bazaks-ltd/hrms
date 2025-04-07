# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EmployeeOvertime(Document):
	pass

@frappe.whitelist()
def get_overtime_approver(employee):
	emp_department = frappe.db.get_value("Employee", employee, ["department"])

	overtime_approver = frappe.db.get_value(
		"Department Approver",
		{"parent": emp_department, "parentfield": "overtime_approvers", "idx": 1},
		"approver",
	)
	return overtime_approver

