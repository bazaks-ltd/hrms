# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from erpnext.setup.doctype.employee.test_employee import make_employee

from hrms.payroll.doctype.new_joiner_salary_structure_assignment.new_joiner_salary_structure_assignment import (
	NewJoinerSalaryStructureAssignment,
)
from hrms.payroll.doctype.salary_structure.test_salary_structure import make_salary_structure
from hrms.tests.test_utils import create_company, create_department, create_employee_grade


class TestNewJoinerSalaryStructureAssignment(IntegrationTestCase):
	def setUp(self):
		create_company()
		create_department("Accounts")
		self.grade = create_employee_grade("Test Grade")

		self.emp1 = make_employee(
			"employee1@njssa.com", company="_Test Company", department="Accounts", grade="Test Grade"
		)
		self.emp2 = make_employee("employee2@njssa.com", company="_Test Company", department="Accounts")
		self.emp3 = make_employee("employee3@njssa.com", company="_Test Company", department="Accounts")
		self.emp4 = make_employee("employee4@njssa.com", company="_Test Company")
		self.emp5 = make_employee("employee5@test.com", company="_Test Company", department="Accounts")

	def tearDown(self):
		frappe.db.rollback()

	def test_get_employees(self):
		today = getdate()

		# create structure and assign to emp2 — should be excluded (any submitted SSA)
		make_salary_structure("Salary Structure NJ 1", "Monthly", self.emp2, today, company="_Test Company")

		args = {
			"doctype": "New Joiner Salary Structure Assignment",
			"department": "Accounts",
		}
		assignment_tool = NewJoinerSalaryStructureAssignment(args)

		advanced_filters = [["Employee", "employee_name", "like", "%njssa%"]]
		employees = assignment_tool.get_employees(advanced_filters)
		employee_names = [d.name for d in employees]

		self.assertNotIn(self.emp2, employee_names)
		self.assertNotIn(self.emp4, employee_names)
		self.assertNotIn(self.emp5, employee_names)
		self.assertEqual(employees[0].base, self.grade.default_base_pay)
		self.assertEqual(employees[1].base, 0)
		self.assertEqual(len(employees), 2)
		self.assertTrue(all(d.date_of_joining for d in employees))

	def test_bulk_assign_structure_uses_doj(self):
		salary_structure = make_salary_structure(
			"Salary Structure NJ 2", "Monthly", company="_Test Company"
		)

		doj = frappe.db.get_value("Employee", self.emp1, "date_of_joining")

		args = {
			"doctype": "New Joiner Salary Structure Assignment",
			"salary_structure": salary_structure,
			"company": "_Test Company",
		}
		assignment_tool = NewJoinerSalaryStructureAssignment(args)

		employees = [
			{"employee": self.emp1, "base": 50000, "variable": 2000},
		]
		assignment_tool.bulk_assign_structure(employees)

		ssa = frappe.get_value(
			"Salary Structure Assignment",
			{"employee": self.emp1},
			["salary_structure", "from_date", "company", "base", "variable"],
			as_dict=1,
		)
		self.assertEqual(ssa.salary_structure, salary_structure.name)
		self.assertEqual(ssa.from_date, getdate(doj))
		self.assertEqual(ssa.company, "_Test Company")
		self.assertEqual(ssa.base, 50000)
		self.assertEqual(ssa.variable, 2000)
