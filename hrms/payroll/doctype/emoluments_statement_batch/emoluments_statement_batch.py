# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document, getdate
from frappe.desk.reportview import get_match_cond
from datetime import date

def get_filtered_employees(
	filters,
	searchfield=None,
	search_string=None,
	fields=None,
	as_dict=False,
	limit=None,
	offset=None,
	ignore_match_conditions=False,
) -> list:
	Employee = frappe.qb.DocType("Employee")

	query = frappe.qb.from_(Employee)

	query = set_fields_to_select(query, fields)
	query = set_searchfield(query, searchfield, search_string, qb_object=Employee)
	query = set_filter_conditions(query, filters, qb_object=Employee)

	if not ignore_match_conditions:
		query = set_match_conditions(query=query, qb_object=Employee)

	if limit:
		query = query.limit(limit)

	if offset:
		query = query.offset(offset)

	return query.run(as_dict=as_dict)


def get_employee_list(
	filters: frappe._dict,
	searchfield=None,
	search_string=None,
	fields: list[str] | None = None,
	as_dict=True,
	limit=None,
	offset=None,
	ignore_match_conditions=False,
) -> list:
	emp_list = get_filtered_employees(
		filters,
		searchfield,
		search_string,
		fields,
		as_dict=as_dict,
		limit=limit,
		offset=offset,
		ignore_match_conditions=ignore_match_conditions,
	)

	if as_dict:
		employees_to_check = {emp.employee: emp for emp in emp_list}
	else:
		employees_to_check = {emp[0]: emp for emp in emp_list}

	return emp_list



class EmolumentsStatementBatch(Document):
	def make_filters(self):
		filters = frappe._dict(
			start_date=self.start_date,
			end_date=self.end_date
		)

		return filters
	
	def on_submit(self):
        # This will be called automatically after the document is submitted
		self.create_emolument_statements()
	
	@frappe.whitelist()
	def print_data(self):
		print("Printing Emoluments Statement Batch Data")

	@frappe.whitelist()
	def create_emolument_statements(self):
		self.check_permission("write")
		employees = [emp.employee for emp in self.employees]

		if employees:
			args = frappe._dict(
				{
					"start_date": self.start_date,
					"end_date": self.end_date,
					"company": self.company,
					"emoluments_statement_batch": self.name,
				}
			)
			if len(employees) > 30 or frappe.flags.enqueue_payroll_entry:
				create_emolument_statements_for_employees(employees, args, publish_progress=False)
				# self.db_set("status", "Queued")
				# frappe.enqueue(
				# 	create_emolument_statements_for_employees,
				# 	timeout=3000,
				# 	employees=employees,
				# 	args=args,
				# 	publish_progress=False,
				# )
				# frappe.msgprint(
				# 	_("Emoluments statement creation is queued. It may take a few minutes"),
				# 	alert=True,
				# 	indicator="blue",
				# )
			else:
				create_emolument_statements_for_employees(employees, args, publish_progress=False)
				# since this method is called via frm.call this doc needs to be updated manually
				self.reload()	

	@frappe.whitelist()
	def fill_employee_details(self):
		filters = self.make_filters()
		employees = get_employee_list(fields=["name", "employee_name", "designation", "department"], filters=filters, as_dict=True, ignore_match_conditions=True)
		self.set("employees", [])

		if not employees:
			error_msg = _(
				"No employees found for the mentioned criteria:<br>Company: {0}"
			).format(
				frappe.bold(self.company)
			)

			if self.start_date:
				error_msg += "<br>" + _("Start date: {0}").format(frappe.bold(self.start_date))
			if self.end_date:
				error_msg += "<br>" + _("End date: {0}").format(frappe.bold(self.end_date))
			frappe.throw(error_msg, title=_("No employees found"))

		child_rows = [{
			"employee": emp["name"], 
			"employee_name": emp["employee_name"],
			"department": emp["department"],
			"designation": emp["designation"]} for emp in employees]

		self.set("employees", child_rows)
		self.number_of_employees = len(self.employees)

		# return self.get_employees_with_unmarked_attendance()

def set_fields_to_select(query, fields: list[str] | None = None):
	default_fields = ["employee", "employee_name", "department", "designation"]

	if fields:
		query = query.select(*fields).distinct()
	else:
		query = query.select(*default_fields).distinct()

	return query


def set_searchfield(query, searchfield, search_string, qb_object):
	if searchfield:
		query = query.where(
			(qb_object[searchfield].like("%" + search_string + "%"))
			| (qb_object.employee_name.like("%" + search_string + "%"))
		)

	return query


def set_filter_conditions(query, filters, qb_object):
	"""Append optional filters to employee query"""
	if filters.get("employees"):
		query = query.where(qb_object.name.notin(filters.get("employees")))

	for fltr_key in ["branch", "department", "designation", "grade"]:
		if filters.get(fltr_key):
			query = query.where(qb_object[fltr_key] == filters[fltr_key])

	return query

def set_match_conditions(query, qb_object):
	match_conditions = get_match_cond("Employee", as_condition=False)

	for cond in match_conditions:
		if isinstance(cond, dict):
			for key, value in cond.items():
				if isinstance(value, list):
					query = query.where(qb_object[key].isin(value))
				else:
					query = query.where(qb_object[key] == value)

	return query

def create_emolument_statements_for_employees(employees, args, publish_progress=True):
	emoluments_statement_batch = frappe.get_doc("Emoluments Statement Batch", args.emoluments_statement_batch)
	try:
		count = 0
		for emp in employees:
			batch_end_month = getdate(emoluments_statement_batch.end_date).month
			batch_end_year = getdate(emoluments_statement_batch.end_date).year
			salary_slip = frappe.get_all(
				"Salary Slip",
				filters={
					"employee": emp,
					"docstatus": 1,
					"end_date": ["<=", args.end_date]
				},
				order_by="end_date desc",
				limit=1,
			)
			if salary_slip:
				slip_doc = frappe.get_doc("Salary Slip", salary_slip[0].name)
				slip_doc.generate_emoluments_statement(emoluments_statement_batch.declaration_date, signatory=emoluments_statement_batch.signatory)
			else:
				print(f"No Salary Slip found for employee {emp} for batch end month.")
			count += 1
			if publish_progress:
				frappe.publish_progress(
					count * 100 / len(employees),
					title=_("Creating Emolument Statements..."),
					)
		emoluments_statement_batch.db_set({"status": "Submitted"})
	except Exception as e:
		frappe.db.rollback()

	finally:
		frappe.db.commit()  # nosemgrep
		frappe.publish_realtime("completed_emolument_statement_creation", user=frappe.session.user)
