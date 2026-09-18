# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.model.naming import make_autoname
from frappe.utils import add_days, cint, flt, formatdate, getdate


class EmployeeHealthInsurance(Document):
	def autoname(self):
		self.name = make_autoname(f"EHI-{self.employee}-.#####")

	def before_insert(self):
		# Data Import leaves Check fields as 0 when the column is blank.
		# A new cover without Valid Upto is the current cover.
		if not self.valid_upto:
			self.is_active = 1

	def validate(self):
		self.set_employee_name()
		self.set_valid_upto_on_deactivate()
		self.validate_date_window()
		if not frappe.flags.in_import:
			self.validate_enrolment_after_previous()
		self.validate_overlap()

	def on_update(self):
		if self.flags.ignore_cover_supersede:
			return
		if cint(self.is_active):
			self.supersede_previous_covers()

	def set_employee_name(self):
		if self.employee and not self.employee_name:
			self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")

	def set_valid_upto_on_deactivate(self):
		if not cint(self.is_active) and not self.valid_upto:
			self.valid_upto = getdate()

	def validate_date_window(self):
		if self.enrolment_date and self.valid_upto and getdate(self.valid_upto) < getdate(self.enrolment_date):
			frappe.throw(_("Valid Upto cannot be before Enrolment Date"))

	def validate_enrolment_after_previous(self):
		if not cint(self.is_active) or not self.employee or not self.enrolment_date:
			return

		previous = self._other_covers(active_only=True)
		enrolment = getdate(self.enrolment_date)
		for row in previous:
			if getdate(row.enrolment_date) >= enrolment:
				frappe.throw(
					_("Enrolment Date must be after the current cover started on {0}").format(
						formatdate(row.enrolment_date)
					)
				)

	def validate_overlap(self):
		if not self.employee or not self.enrolment_date:
			return

		start = getdate(self.enrolment_date)
		end = getdate(self.valid_upto) if self.valid_upto else None

		for other in self._other_covers():
			# Active rows are closed on save of a new active cover.
			if cint(self.is_active) and cint(other.is_active):
				continue
			other_start = getdate(other.enrolment_date)
			other_end = getdate(other.valid_upto) if other.valid_upto else None
			if windows_overlap(start, end, other_start, other_end):
				frappe.throw(
					_("Cover dates overlap with {0} ({1} to {2})").format(
						other.name,
						formatdate(other.enrolment_date),
						formatdate(other.valid_upto) if other.valid_upto else _("Open"),
					)
				)

	def supersede_previous_covers(self):
		close_date = add_days(getdate(self.enrolment_date), -1)
		for row in self._other_covers(active_only=True):
			values = {"is_active": 0, "superseded_by": self.name}
			if not row.valid_upto:
				row_start = getdate(row.enrolment_date)
				values["valid_upto"] = close_date if close_date >= row_start else row_start
			frappe.db.set_value("Employee Health Insurance", row.name, values, update_modified=True)

	def _other_covers(self, active_only=False):
		filters = {"employee": self.employee}
		if self.name:
			filters["name"] = ["!=", self.name]
		if active_only:
			filters["is_active"] = 1
		return frappe.get_all(
			"Employee Health Insurance",
			filters=filters,
			fields=["name", "enrolment_date", "valid_upto", "is_active"],
		)


def windows_overlap(start1, end1, start2, end2):
	open_end = getdate("9999-12-31")
	return start1 <= (end2 or open_end) and start2 <= (end1 or open_end)


def get_applicable_cover(employee, start_date=None, end_date=None):
	"""Return the cover whose window includes the salary period."""
	if not employee or not end_date:
		return None

	end_date = getdate(end_date)
	start_date = getdate(start_date) if start_date else end_date

	covers = frappe.db.sql(
		"""
		SELECT
			name,
			self_deduction,
			dependent_deduction,
			employer_contribution
		FROM `tabEmployee Health Insurance`
		WHERE employee = %s
			AND enrolment_date <= %s
			AND (
				(valid_upto IS NOT NULL AND valid_upto >= %s)
				OR (valid_upto IS NULL AND is_active = 1)
			)
		ORDER BY enrolment_date DESC
		LIMIT 1
		""",
		(employee, end_date, start_date),
		as_dict=True,
	)
	return covers[0] if covers else None


@frappe.whitelist()
def make_new_cover(source_name, target_doc=None):
	def set_missing_values(source, target):
		target.enrolment_date = getdate()
		target.is_active = 1
		target.valid_upto = None
		target.superseded_by = None

	return get_mapped_doc(
		"Employee Health Insurance",
		source_name,
		{
			"Employee Health Insurance": {
				"doctype": "Employee Health Insurance",
				"field_no_map": ["valid_upto", "superseded_by", "enrolment_date", "is_active"],
			},
			"Insurance Dependent": {
				"doctype": "Insurance Dependent",
			},
		},
		target_doc,
		set_missing_values,
	)


@frappe.whitelist()
def get_cover_history(employee, exclude=None):
	if not employee:
		return []

	filters = {"employee": employee}
	if exclude:
		filters["name"] = ["!=", exclude]

	return frappe.get_all(
		"Employee Health Insurance",
		filters=filters,
		fields=[
			"name",
			"enrolment_date",
			"valid_upto",
			"is_active",
			"self_deduction",
			"dependent_deduction",
			"employer_contribution",
			"inpatient_cover",
			"outpatient_cover",
			"insurance_catastrophe_cover",
			"dependent_catastrophe_cover",
			"superseded_by",
		],
		order_by="enrolment_date desc, creation desc",
	)


@frappe.whitelist()
def get_employees_without_cover_count():
	count = frappe.db.sql(
		"""
		SELECT COUNT(*)
		FROM `tabEmployee` e
		LEFT JOIN `tabEmployee Health Insurance` ehi
			ON ehi.employee = e.name AND ehi.is_active = 1
		WHERE e.status = 'Active' AND ehi.name IS NULL
		"""
	)[0][0]
	return {"value": cint(count), "fieldtype": "Int"}


@frappe.whitelist()
def get_active_ee_deduction():
	total = frappe.db.sql(
		"""
		SELECT SUM(IFNULL(self_deduction, 0) + IFNULL(dependent_deduction, 0))
		FROM `tabEmployee Health Insurance`
		WHERE is_active = 1
		"""
	)[0][0]
	return {"value": flt(total), "fieldtype": "Currency"}
