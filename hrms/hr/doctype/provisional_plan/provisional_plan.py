# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

# import frappe
import dateutil.parser
from frappe.model.document import Document
import frappe
import json
import dateutil
import datetime
import calendar

from itertools import chain

class ProvisionalPlan(Document):
	pass


@frappe.whitelist()
def create_shifts(provisional_plan):
	doc = frappe.get_doc("Provisional Plan", provisional_plan)
	employees = doc.employees
	shifts = json.loads(doc.shifts)
	start_date = doc.start_date
	department = frappe.get_doc("Department", doc.department)
	company = department.company

	first_date_of_month = datetime.datetime(start_date.year, start_date.month, 1)
	start_date_index = int((start_date - datetime.timedelta(days=start_date.weekday())).strftime("%d"))
	flat_shifts = list(chain.from_iterable(shifts))
	num_days = calendar.monthrange(start_date.year, start_date.month)[1]

	result_shifts = []
	for ei, employee in enumerate(employees):
		for i in range(num_days):
			shift_index = (i + 1 - (start_date_index - (ei * 7))) % len(flat_shifts)
			s = ""
			if shift_index >= 0:
				s = flat_shifts[shift_index]
			else:
				s = flat_shifts[len(flat_shifts) + shift_index]

			if s != "R":

				shift_assignment = [
					f"R-{employee.employee}-{(first_date_of_month + datetime.timedelta(days=i)).strftime('%Y-%m-%d')}-{department.name}",
					 employee.employee,
					 (first_date_of_month + datetime.timedelta(days=i)).strftime("%Y-%m-%d"),
					 s,
					 department.name,
					 company,
					 True,
					 "Active"
				]
				result_shifts.append(shift_assignment)


	frappe.db.bulk_insert("Shift Assignment",
					    fields=["name","employee","start_date","shift_type","department","company","docstatus","status"],
						  values=result_shifts)

	frappe.db.set_value('Provisional Plan', provisional_plan, 'real_shift_assigned', 1)






	return result_shifts
