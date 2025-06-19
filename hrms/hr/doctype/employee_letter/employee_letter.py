# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EmployeeLetter(Document):
	@frappe.whitelist()
	def get_formatted_content(self):
		"""Process template with employee data and return formatted content"""
		
		# Get template content
		template_doc = frappe.get_doc("Employee Letter Template", self.letter_type)
		template_content = template_doc.content
		
		# Get employee data
		employee = frappe.get_doc("Employee", self.employee)
		
		# Prepare context data
		context = {
			'employee': employee,
			'letter_date': self.letter_date,
			'company': frappe.get_doc("Company", employee.company),
		}
		
		# Process template with Jinja2
		from jinja2 import Template
		template = Template(template_content)
		formatted_content = template.render(**context)
		
		return formatted_content
