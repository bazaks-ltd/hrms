import frappe


def execute():
	"""Submitted salary slips are reviewed by definition; drafts/cancelled are not."""
	frappe.db.sql(
		"""
		UPDATE `tabSalary Slip`
		SET payroll_reviewed = 1
		WHERE docstatus = 1 AND IFNULL(payroll_reviewed, 0) = 0
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabSalary Slip`
		SET payroll_reviewed = 0
		WHERE docstatus != 1 AND IFNULL(payroll_reviewed, 0) = 1
		"""
	)

	# Refresh Payroll Entry readiness flag from current slip states
	payroll_entries = frappe.get_all(
		"Payroll Entry",
		filters={"docstatus": 1},
		pluck="name",
	)
	for pe_name in payroll_entries:
		has_draft = frappe.db.exists(
			"Salary Slip", {"payroll_entry": pe_name, "docstatus": 0}
		)
		submitted = frappe.get_all(
			"Salary Slip",
			filters={"payroll_entry": pe_name, "docstatus": 1},
			fields=["payroll_reviewed"],
		)
		reviewed = bool(submitted) and not has_draft and all(
			frappe.utils.cint(s.payroll_reviewed) for s in submitted
		)
		frappe.db.set_value(
			"Payroll Entry", pe_name, "payslips_reviewed", frappe.utils.cint(reviewed), update_modified=False
		)
