# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.desk.reportview import get_match_cond
from frappe.utils import getdate
from datetime import date


def get_mauritius_fiscal_year(for_date):
	"""Return (start, end) for Mauritius FY 1 Jul → 30 Jun containing for_date."""
	for_date = getdate(for_date)
	if for_date.month >= 7:
		return date(for_date.year, 7, 1), date(for_date.year + 1, 6, 30)
	return date(for_date.year - 1, 7, 1), date(for_date.year, 6, 30)


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

	return emp_list


class EmolumentsStatementBatch(Document):
	def validate(self):
		self.normalize_mauritius_fy_dates()

	def normalize_mauritius_fy_dates(self):
		"""Normalize start/end to Mauritius FY containing the entered date."""
		anchor = self.start_date or self.end_date
		if not anchor:
			return

		fy_start, fy_end = get_mauritius_fiscal_year(anchor)

		# If both dates are set but span different FYs, prefer end_date as anchor
		if self.start_date and self.end_date:
			start_fy = get_mauritius_fiscal_year(self.start_date)
			end_fy = get_mauritius_fiscal_year(self.end_date)
			if start_fy != end_fy:
				fy_start, fy_end = end_fy

		self.start_date = fy_start
		self.end_date = fy_end

	def make_filters(self):
		filters = frappe._dict(start_date=self.start_date, end_date=self.end_date)
		return filters

	def on_submit(self):
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
			else:
				create_emolument_statements_for_employees(employees, args, publish_progress=False)
				# since this method is called via frm.call this doc needs to be updated manually
				self.reload()

	@frappe.whitelist()
	def fill_employee_details(self):
		filters = self.make_filters()
		employees = get_employee_list(
			fields=["name", "employee_name", "designation", "department"],
			filters=filters,
			as_dict=True,
			ignore_match_conditions=True,
		)
		self.set("employees", [])

		if not employees:
			error_msg = _(
				"No employees found for the mentioned criteria:<br>Company: {0}"
			).format(frappe.bold(self.company))

			if self.start_date:
				error_msg += "<br>" + _("Start date: {0}").format(frappe.bold(self.start_date))
			if self.end_date:
				error_msg += "<br>" + _("End date: {0}").format(frappe.bold(self.end_date))
			frappe.throw(error_msg, title=_("No employees found"))

		child_rows = [
			{
				"employee": emp["name"],
				"employee_name": emp["employee_name"],
				"department": emp["department"],
				"designation": emp["designation"],
			}
			for emp in employees
		]

		self.set("employees", child_rows)
		if hasattr(self, "number_of_employees"):
			self.number_of_employees = len(self.employees)


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
	emoluments_statement_batch = frappe.get_doc(
		"Emoluments Statement Batch", args.emoluments_statement_batch
	)
	emoluments_statement_batch.db_set("status", "In Progress")
	emoluments_statement_batch.db_set("failure_log", "")

	errors = []
	success_count = 0
	count = 0

	def set_row_result(row, status, error_message=None, statement_name=None):
		if not row:
			return
		values = {"status": status, "error_message": error_message or ""}
		if statement_name:
			values["statement_of_emoluments"] = statement_name
		frappe.db.set_value("Emoluments Statement Batch Employee", row.name, values)

	def log_failure(emp, message, with_traceback=False):
		employee_name = frappe.db.get_value("Employee", emp, "employee_name") or emp
		line = f"{emp} ({employee_name}): {message}"
		errors.append(line)
		if with_traceback:
			frappe.log_error(
				title=_("Emoluments Statement Batch {0} — {1}").format(
					emoluments_statement_batch.name, emp
				),
				message=frappe.get_traceback(),
			)
		else:
			frappe.log_error(
				title=_("Emoluments Statement Batch {0} — {1}").format(
					emoluments_statement_batch.name, emp
				),
				message=line,
			)

	try:
		employee_row_map = {row.employee: row for row in emoluments_statement_batch.employees}

		for emp in employees:
			row = employee_row_map.get(emp)

			# Skip employees that already have a linked statement (retry-safe)
			if row and row.statement_of_emoluments:
				set_row_result(row, "Skipped", _("Already generated: {0}").format(row.statement_of_emoluments))
				success_count += 1
				count += 1
				if publish_progress:
					frappe.publish_progress(
						count * 100 / len(employees),
						title=_("Creating Emolument Statements..."),
					)
				continue

			try:
				salary_slip = frappe.get_all(
					"Salary Slip",
					filters={
						"employee": emp,
						"docstatus": 1,
						"end_date": ["between", [args.start_date, args.end_date]],
					},
					order_by="end_date desc",
					limit=1,
				)
				if not salary_slip:
					msg = _("No Salary Slip found in the selected fiscal year ({0} to {1}).").format(
						args.start_date, args.end_date
					)
					set_row_result(row, "Failed", msg)
					log_failure(emp, msg)
					count += 1
					if publish_progress:
						frappe.publish_progress(
							count * 100 / len(employees),
							title=_("Creating Emolument Statements..."),
						)
					continue

				slip_doc = frappe.get_doc("Salary Slip", salary_slip[0].name)
				statement = slip_doc.generate_emoluments_statement(
					period_start_date=emoluments_statement_batch.start_date,
					period_end_date=emoluments_statement_batch.end_date,
					declaration_date=emoluments_statement_batch.declaration_date,
					signatory=emoluments_statement_batch.signatory,
				)

				set_row_result(row, "Success", statement_name=statement.name)
				success_count += 1
			except Exception as e:
				set_row_result(row, "Failed", str(e))
				log_failure(emp, str(e), with_traceback=True)

			count += 1
			if publish_progress:
				frappe.publish_progress(
					count * 100 / len(employees),
					title=_("Creating Emolument Statements..."),
				)

		failure_log = ""
		if errors:
			failure_log = _("Batch {0} — {1} succeeded, {2} failed\n\n{3}").format(
				emoluments_statement_batch.name,
				success_count,
				len(errors),
				"\n".join(errors),
			)
			emoluments_statement_batch.db_set(
				{"status": "Failed", "failure_log": failure_log}
			)
			frappe.log_error(
				title=_("Emoluments Statement Batch {0} — summary").format(
					emoluments_statement_batch.name
				),
				message=failure_log,
			)
			frappe.msgprint(
				_("Created {0} statement(s). {1} failed. See Failure Log on this batch and Error Log.").format(
					success_count, len(errors)
				),
				title=_("Partial Failure") if success_count else _("Failed"),
				indicator="orange" if success_count else "red",
			)
		else:
			emoluments_statement_batch.db_set(
				{
					"status": "Completed",
					"failure_log": _("All {0} statement(s) created successfully.").format(success_count),
				}
			)

	except Exception:
		frappe.db.rollback()
		emoluments_statement_batch.db_set(
			{
				"status": "Failed",
				"failure_log": frappe.get_traceback(),
			}
		)
		frappe.log_error(
			title=_("Emoluments Statement Batch {0} Failed").format(emoluments_statement_batch.name),
			message=frappe.get_traceback(),
		)
		raise

	finally:
		frappe.db.commit()  # nosemgrep
		frappe.publish_realtime("completed_emolument_statement_creation", user=frappe.session.user)
