# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EmolumentsStatementBatchEmployee(Document):
	def generate_statements(self):
		for row in self.employees:
			try:
				slip = frappe.get_all(
					"Salary Slip",
					filters={
						"employee": row.employee,
						"start_date": [">=", self.from_date],
						"end_date": ["<=", self.to_date],
						"docstatus": 1,
					},
					order_by="end_date desc",
					limit=1,
				)
				if not slip:
					row.status = "Failed"
					row.error_message = "No salary slip found"
					continue

				slip_doc = frappe.get_doc("Salary Slip", slip[0].name)
				statement = slip_doc.generate_emoluments_statement()
				row.statement = statement.name
				row.status = "Success"
				row.error_message = ""
			except Exception as e:
				row.status = "Failed"
				row.error_message = str(e)
		self.status = "Completed"
		self.save()
