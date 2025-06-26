# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate

class NewHireTrainingPlan(Document):

	@frappe.whitelist()
	def apply_training_template(self, template_name):
		print("Applying training template...")
		"""Apply a training template to an existing training plan"""
		template = frappe.get_doc("New Hire Training Plan Template", template_name)
		
		# Clear existing assignments if any
		self.training_assignments = []
		
		# Apply template assignments
		for template_assignment in template.template_assignments:
			start_date = self.start_date or nowdate()
			due_date = frappe.utils.add_days(start_date, template_assignment.duration_days or 7)
			
			self.append("training_assignments", {
				"assignment_name": template_assignment.assignment_name,
				"course": template_assignment.course,
				"trainer": template_assignment.default_trainer,
				"started_on": start_date,
				"due_on": due_date,
				"progress": "Not Started",
				"percent_complete": 0,
			})
		
		self.save()
		frappe.msgprint(f"Template '{template_name}' applied successfully with {len(template.template_assignments)} assignments")
		return self
