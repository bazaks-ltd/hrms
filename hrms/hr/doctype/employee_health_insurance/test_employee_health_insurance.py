# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from erpnext.setup.doctype.employee.test_employee import make_employee

from hrms.hr.doctype.employee_health_insurance.employee_health_insurance import get_applicable_cover


class TestEmployeeHealthInsurance(IntegrationTestCase):
	def setUp(self):
		self.employee = make_employee("ehi.cover.test@example.com")
		for name in frappe.get_all(
			"Employee Health Insurance",
			filters={"employee": self.employee},
			pluck="name",
		):
			frappe.delete_doc("Employee Health Insurance", name, force=1, ignore_permissions=True)

	def _make_cover(self, enrolment_date, is_active=1, **kwargs):
		doc = frappe.get_doc(
			{
				"doctype": "Employee Health Insurance",
				"employee": self.employee,
				"enrolment_date": enrolment_date,
				"is_active": is_active,
				"self_deduction": kwargs.get("self_deduction", 100),
				"dependent_deduction": kwargs.get("dependent_deduction", 50),
				"employer_contribution": kwargs.get("employer_contribution", 200),
				"inpatient_cover": kwargs.get("inpatient_cover", 1),
				"outpatient_cover": kwargs.get("outpatient_cover", 1),
				"catastrophe_cover": kwargs.get("catastrophe_cover", 0),
				"valid_upto": kwargs.get("valid_upto"),
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_new_cover_disables_previous(self):
		first = self._make_cover("2026-01-01", self_deduction=100)
		second = self._make_cover("2026-06-01", self_deduction=150)

		first.reload()
		self.assertEqual(second.is_active, 1)
		self.assertEqual(first.is_active, 0)
		self.assertEqual(getdate(first.valid_upto), getdate("2026-05-31"))
		self.assertEqual(first.superseded_by, second.name)

	def test_applicable_cover_uses_date_window(self):
		old = self._make_cover("2026-01-01", self_deduction=100)
		self._make_cover("2026-06-01", self_deduction=150)

		january = get_applicable_cover(self.employee, "2026-01-01", "2026-01-31")
		june = get_applicable_cover(self.employee, "2026-06-01", "2026-06-30")

		self.assertEqual(january.name, old.name)
		self.assertEqual(january.self_deduction, 100)
		self.assertEqual(june.self_deduction, 150)
