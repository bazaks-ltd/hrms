import frappe


def execute():
	"""mode_of_payment on Salary Slip is now Link → Mode of Payment (was Select salary_mode)."""
	invalid = frappe.db.sql(
		"""
		SELECT ss.name
		FROM `tabSalary Slip` ss
		LEFT JOIN `tabMode of Payment` mop ON mop.name = ss.mode_of_payment
		WHERE IFNULL(ss.mode_of_payment, '') != ''
			AND mop.name IS NULL
		"""
	)
	for (name,) in invalid:
		frappe.db.set_value("Salary Slip", name, "mode_of_payment", None, update_modified=False)
