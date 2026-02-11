# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import datetime

import frappe
from frappe import _, qb
from frappe.model.document import Document
from frappe.query_builder import Criterion
from frappe.query_builder.custom import ConstantColumn
from frappe.utils import (
	add_days,
	add_months,
	cint,
	comma_and,
	cstr,
	flt,
	format_datetime,
	formatdate,
	get_datetime,
	get_first_day,
	get_last_day,
	get_link_to_form,
	get_number_format_info,
	getdate,
	nowdate,
)

import erpnext
from erpnext import get_company_currency
from erpnext.setup.doctype.employee.employee import (
	InactiveEmployeeStatusError,
	get_holiday_list_for_employee,
)

from hrms.hr.doctype.leave_policy_assignment.leave_policy_assignment import (
	calculate_pro_rated_leaves,
)

DateTimeLikeObject = str | datetime.date | datetime.datetime


class DuplicateDeclarationError(frappe.ValidationError):
	pass


def set_employee_name(doc):
	if doc.employee and not doc.employee_name:
		doc.employee_name = frappe.db.get_value("Employee", doc.employee, "employee_name")


def update_employee_work_history(employee, details, date=None, cancel=False):
	if not details:
		return employee

	if not employee.internal_work_history and not cancel:
		employee.append(
			"internal_work_history",
			{
				"branch": employee.branch,
				"designation": employee.designation,
				"department": employee.department,
				"from_date": employee.date_of_joining,
			},
		)

	internal_work_history = {}
	for item in details:
		field = frappe.get_meta("Employee").get_field(item.fieldname)
		if not field:
			continue

		new_value = item.new if not cancel else item.current
		new_value = get_formatted_value(new_value, field.fieldtype)
		setattr(employee, item.fieldname, new_value)

		if item.fieldname in ["department", "designation", "branch"]:
			internal_work_history[item.fieldname] = item.new

	if internal_work_history and not cancel:
		internal_work_history["from_date"] = date
		employee.append("internal_work_history", internal_work_history)

	if cancel:
		delete_employee_work_history(details, employee, date)

	update_to_date_in_work_history(employee, cancel)

	return employee


def get_formatted_value(value, fieldtype):
	"""
	Since the fields in Internal Work History table are `Data` fields
	format them as per relevant field types
	"""
	if not value:
		return

	if fieldtype == "Date":
		value = getdate(value)
	elif fieldtype == "Datetime":
		value = get_datetime(value)
	elif fieldtype in ["Currency", "Float"]:
		# in case of currency/float, the value might be in user's prefered number format
		# instead of machine readable format. Convert it into a machine readable format
		number_format = frappe.db.get_default("number_format") or "#,###.##"
		decimal_str, comma_str, _number_format_precision = get_number_format_info(number_format)

		if comma_str == "." and decimal_str == ",":
			value = value.replace(",", "#$")
			value = value.replace(".", ",")
			value = value.replace("#$", ".")

		value = flt(value)

	return value


def delete_employee_work_history(details, employee, date):
	filters = {}
	for d in details:
		for history in employee.internal_work_history:
			if d.property == "Department" and history.department == d.new:
				department = d.new
				filters["department"] = department
			if d.property == "Designation" and history.designation == d.new:
				designation = d.new
				filters["designation"] = designation
			if d.property == "Branch" and history.branch == d.new:
				branch = d.new
				filters["branch"] = branch
			if date and date == history.from_date:
				filters["from_date"] = date
	if filters:
		frappe.db.delete("Employee Internal Work History", filters)
		employee.save()


def update_to_date_in_work_history(employee, cancel):
	if not employee.internal_work_history:
		return

	for idx, row in enumerate(employee.internal_work_history):
		if not row.from_date or idx == 0:
			continue

		prev_row = employee.internal_work_history[idx - 1]
		if not prev_row.to_date:
			prev_row.to_date = add_days(row.from_date, -1)

	if cancel:
		employee.internal_work_history[-1].to_date = None


@frappe.whitelist()
def get_employee_field_property(employee, fieldname):
	if not (employee and fieldname):
		return

	field = frappe.get_meta("Employee").get_field(fieldname)
	if not field:
		return

	value = frappe.db.get_value("Employee", employee, fieldname)
	if field.fieldtype == "Date":
		value = formatdate(value)
	elif field.fieldtype == "Datetime":
		value = format_datetime(value)

	return {
		"value": value,
		"datatype": field.fieldtype,
		"label": field.label,
		"options": field.options,
	}


def validate_dates(doc, from_date, to_date, restrict_future_dates=True):
	date_of_joining, relieving_date = frappe.db.get_value(
		"Employee", doc.employee, ["date_of_joining", "relieving_date"]
	)
	if getdate(from_date) > getdate(to_date):
		frappe.throw(_("To date can not be less than from date"))
	elif getdate(from_date) > getdate(nowdate()) and restrict_future_dates:
		frappe.throw(_("Future dates not allowed"))
	elif date_of_joining and getdate(from_date) < getdate(date_of_joining):
		frappe.throw(_("From date can not be less than employee's joining date"))
	elif relieving_date and getdate(to_date) > getdate(relieving_date):
		frappe.throw(_("To date can not greater than employee's relieving date"))


def validate_overlap(doc, from_date, to_date, company=None):
	query = """
		select name
		from `tab{0}`
		where name != %(name)s
		"""
	query += get_doc_condition(doc.doctype)

	if not doc.name:
		# hack! if name is null, it could cause problems with !=
		doc.name = "New " + doc.doctype

	overlap_doc = frappe.db.sql(
		query.format(doc.doctype),
		{
			"employee": doc.get("employee"),
			"from_date": from_date,
			"to_date": to_date,
			"name": doc.name,
			"company": company,
		},
		as_dict=1,
	)

	if overlap_doc:
		if doc.get("employee"):
			exists_for = doc.employee
		if company:
			exists_for = company
		throw_overlap_error(doc, exists_for, overlap_doc[0].name, from_date, to_date)


def get_doc_condition(doctype):
	if doctype == "Compensatory Leave Request":
		return "and employee = %(employee)s and docstatus < 2 \
		and (work_from_date between %(from_date)s and %(to_date)s \
		or work_end_date between %(from_date)s and %(to_date)s \
		or (work_from_date < %(from_date)s and work_end_date > %(to_date)s))"
	elif doctype == "Leave Period":
		return "and company = %(company)s and (from_date between %(from_date)s and %(to_date)s \
			or to_date between %(from_date)s and %(to_date)s \
			or (from_date < %(from_date)s and to_date > %(to_date)s))"


def throw_overlap_error(doc, exists_for, overlap_doc, from_date, to_date):
	msg = (
		_("A {0} exists between {1} and {2} (").format(
			doc.doctype, formatdate(from_date), formatdate(to_date)
		)
		+ f""" <b><a href="/app/Form/{doc.doctype}/{overlap_doc}">{overlap_doc}</a></b>"""
		+ _(") for {0}").format(exists_for)
	)
	frappe.throw(msg)


def validate_duplicate_exemption_for_payroll_period(doctype, docname, payroll_period, employee):
	existing_record = frappe.db.exists(
		doctype,
		{
			"payroll_period": payroll_period,
			"employee": employee,
			"docstatus": ["<", 2],
			"name": ["!=", docname],
		},
	)
	if existing_record:
		frappe.throw(
			_("{0} already exists for employee {1} and period {2}").format(doctype, employee, payroll_period),
			DuplicateDeclarationError,
		)


def validate_tax_declaration(declarations):
	subcategories = []
	for d in declarations:
		if d.exemption_sub_category in subcategories:
			frappe.throw(_("More than one selection for {0} not allowed").format(d.exemption_sub_category))
		subcategories.append(d.exemption_sub_category)


def get_total_exemption_amount(declarations):
	exemptions = frappe._dict()
	for d in declarations:
		exemptions.setdefault(d.exemption_category, frappe._dict())
		category_max_amount = exemptions.get(d.exemption_category).max_amount
		if not category_max_amount:
			category_max_amount = frappe.db.get_value(
				"Employee Tax Exemption Category", d.exemption_category, "max_amount"
			)
			exemptions.get(d.exemption_category).max_amount = category_max_amount
		sub_category_exemption_amount = (
			d.max_amount if (d.max_amount and flt(d.amount) > flt(d.max_amount)) else d.amount
		)

		exemptions.get(d.exemption_category).setdefault("total_exemption_amount", 0.0)
		exemptions.get(d.exemption_category).total_exemption_amount += flt(sub_category_exemption_amount)

		if (
			category_max_amount
			and exemptions.get(d.exemption_category).total_exemption_amount > category_max_amount
		):
			exemptions.get(d.exemption_category).total_exemption_amount = category_max_amount

	total_exemption_amount = sum([flt(d.total_exemption_amount) for d in exemptions.values()])
	return total_exemption_amount


@frappe.whitelist()
def get_leave_period(from_date, to_date, company):
	leave_period = frappe.db.sql(
		"""
		select name, from_date, to_date
		from `tabLeave Period`
		where company=%(company)s and is_active=1
			and (from_date between %(from_date)s and %(to_date)s
				or to_date between %(from_date)s and %(to_date)s
				or (from_date < %(from_date)s and to_date > %(to_date)s))
	""",
		{"from_date": from_date, "to_date": to_date, "company": company},
		as_dict=1,
	)

	if leave_period:
		return leave_period


def generate_leave_encashment():
	"""Generates a draft leave encashment on allocation expiry"""
	from hrms.hr.doctype.leave_encashment.leave_encashment import create_leave_encashment

	if frappe.db.get_single_value("HR Settings", "auto_leave_encashment"):
		leave_type = frappe.get_all("Leave Type", filters={"allow_encashment": 1}, fields=["name"])
		leave_type = [l["name"] for l in leave_type]

		leave_allocation = frappe.get_all(
			"Leave Allocation",
			filters={"to_date": add_days(getdate(), -1), "leave_type": ("in", leave_type)},
			fields=[
				"employee",
				"leave_period",
				"leave_type",
				"to_date",
				"total_leaves_allocated",
				"new_leaves_allocated",
			],
		)

		create_leave_encashment(leave_allocation=leave_allocation)


def allocate_earned_leaves():
	"""Allocate earned leaves to Employees"""
	e_leave_types = get_earned_leaves()
	today = frappe.flags.current_date or getdate()

	for e_leave_type in e_leave_types:
		leave_allocations = get_leave_allocations(today, e_leave_type.name)
		for allocation in leave_allocations:
			if not allocation.leave_policy_assignment and not allocation.leave_policy:
				continue

			leave_policy = (
				allocation.leave_policy
				if allocation.leave_policy
				else frappe.db.get_value(
					"Leave Policy Assignment", allocation.leave_policy_assignment, ["leave_policy"]
				)
			)

			annual_allocation = frappe.db.get_value(
				"Leave Policy Detail",
				filters={"parent": leave_policy, "leave_type": e_leave_type.name},
				fieldname=["annual_allocation"],
			)
			date_of_joining = frappe.db.get_value("Employee", allocation.employee, "date_of_joining")

			from_date = allocation.from_date

			if e_leave_type.allocate_on_day == "Date of Joining":
				from_date = date_of_joining

			if check_effective_date(
				from_date, today, e_leave_type.earned_leave_frequency, e_leave_type.allocate_on_day
			):
				update_previous_leave_allocation(allocation, annual_allocation, e_leave_type, date_of_joining)


def update_previous_leave_allocation(allocation, annual_allocation, e_leave_type, date_of_joining):
	allocation = frappe.get_doc("Leave Allocation", allocation.name)
	annual_allocation = flt(annual_allocation, allocation.precision("total_leaves_allocated"))

	earned_leaves = get_monthly_earned_leave(
		date_of_joining,
		annual_allocation,
		e_leave_type.earned_leave_frequency,
		e_leave_type.rounding,
	)

	new_allocation = flt(allocation.total_leaves_allocated) + flt(earned_leaves)
	new_allocation_without_cf = flt(
		flt(allocation.get_existing_leave_count()) + flt(earned_leaves),
		allocation.precision("total_leaves_allocated"),
	)

	if new_allocation > e_leave_type.max_leaves_allowed and e_leave_type.max_leaves_allowed > 0:
		new_allocation = e_leave_type.max_leaves_allowed

	if (
		new_allocation != allocation.total_leaves_allocated
		# annual allocation as per policy should not be exceeded
		and new_allocation_without_cf <= annual_allocation
	):
		today_date = frappe.flags.current_date or getdate()

		allocation.db_set("total_leaves_allocated", new_allocation, update_modified=False)
		create_additional_leave_ledger_entry(allocation, earned_leaves, today_date)

		if e_leave_type.allocate_on_day:
			text = _(
				"Allocated {0} leave(s) via scheduler on {1} based on the 'Allocate on Day' option set to {2}"
			).format(
				frappe.bold(earned_leaves), frappe.bold(formatdate(today_date)), e_leave_type.allocate_on_day
			)

		allocation.add_comment(comment_type="Info", text=text)


@frappe.whitelist()
def get_monthly_earned_leave(
	date_of_joining,
	annual_leaves,
	frequency,
	rounding,
	period_start_date=None,
	period_end_date=None,
	pro_rated=True,
):
	earned_leaves = 0.0
	divide_by_frequency = {"Yearly": 1, "Half-Yearly": 2, "Quarterly": 4, "Monthly": 12}
	if annual_leaves:
		earned_leaves = flt(annual_leaves) / divide_by_frequency[frequency]

		if pro_rated:
			if not (period_start_date or period_end_date):
				today_date = frappe.flags.current_date or getdate()
				period_end_date = get_last_day(today_date)
				period_start_date = get_first_day(today_date)

			earned_leaves = calculate_pro_rated_leaves(
				earned_leaves, date_of_joining, period_start_date, period_end_date, is_earned_leave=True
			)

		earned_leaves = round_earned_leaves(earned_leaves, rounding)

	return earned_leaves


def round_earned_leaves(earned_leaves, rounding):
	if not rounding:
		return earned_leaves

	if rounding == "0.25":
		earned_leaves = round(earned_leaves * 4) / 4
	elif rounding == "0.5":
		earned_leaves = round(earned_leaves * 2) / 2
	else:
		earned_leaves = round(earned_leaves)

	return earned_leaves


def get_leave_allocations(date, leave_type):
	employee = frappe.qb.DocType("Employee")
	leave_allocation = frappe.qb.DocType("Leave Allocation")
	query = (
		frappe.qb.from_(leave_allocation)
		.join(employee)
		.on(leave_allocation.employee == employee.name)
		.select(
			leave_allocation.name,
			leave_allocation.employee,
			leave_allocation.from_date,
			leave_allocation.to_date,
			leave_allocation.leave_policy_assignment,
			leave_allocation.leave_policy,
		)
		.where(
			(date >= leave_allocation.from_date)
			& (date <= leave_allocation.to_date)
			& (leave_allocation.docstatus == 1)
			& (leave_allocation.leave_type == leave_type)
			& (employee.status != "Left")
		)
	)
	return query.run(as_dict=1) or []


def get_earned_leaves():
	return frappe.get_all(
		"Leave Type",
		fields=[
			"name",
			"max_leaves_allowed",
			"earned_leave_frequency",
			"rounding",
			"allocate_on_day",
		],
		filters={"is_earned_leave": 1},
	)


def create_additional_leave_ledger_entry(allocation, leaves, date):
	"""Create leave ledger entry for leave types"""
	allocation.new_leaves_allocated = leaves
	allocation.from_date = date
	allocation.unused_leaves = 0
	allocation.create_leave_ledger_entry()


def check_effective_date(from_date, today, frequency, allocate_on_day):
	from dateutil import relativedelta

	from_date = get_datetime(from_date)
	today = frappe.flags.current_date or get_datetime(today)
	rd = relativedelta.relativedelta(today, from_date)

	expected_date = {
		"First Day": get_first_day(today),
		"Last Day": get_last_day(today),
		"Date of Joining": from_date,
	}[allocate_on_day]

	if expected_date.day == today.day:
		if frequency == "Monthly":
			return True
		elif frequency == "Quarterly" and rd.months % 3:
			return True
		elif frequency == "Half-Yearly" and rd.months % 6:
			return True
		elif frequency == "Yearly" and rd.months % 12:
			return True

	return False


def get_salary_assignments(employee, payroll_period):
	start_date, end_date = frappe.db.get_value("Payroll Period", payroll_period, ["start_date", "end_date"])
	assignments = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1, "from_date": ["between", (start_date, end_date)]},
		fields=["*"],
		order_by="from_date",
	)

	if not assignments:
		# if no assignments found for the given period
		# get the last one assigned before the period that is still active
		assignments = frappe.get_all(
			"Salary Structure Assignment",
			filters={"employee": employee, "docstatus": 1, "from_date": ["<=", start_date]},
			fields=["*"],
			order_by="from_date desc",
			limit=1,
		)

	return assignments


def get_sal_slip_total_benefit_given(employee, payroll_period, component=False):
	total_given_benefit_amount = 0
	query = """
	select sum(sd.amount) as total_amount
	from `tabSalary Slip` ss, `tabSalary Detail` sd
	where ss.employee=%(employee)s
	and ss.docstatus = 1 and ss.name = sd.parent
	and sd.is_flexible_benefit = 1 and sd.parentfield = "earnings"
	and sd.parenttype = "Salary Slip"
	and (ss.start_date between %(start_date)s and %(end_date)s
		or ss.end_date between %(start_date)s and %(end_date)s
		or (ss.start_date < %(start_date)s and ss.end_date > %(end_date)s))
	"""

	if component:
		query += "and sd.salary_component = %(component)s"

	sum_of_given_benefit = frappe.db.sql(
		query,
		{
			"employee": employee,
			"start_date": payroll_period.start_date,
			"end_date": payroll_period.end_date,
			"component": component,
		},
		as_dict=True,
	)

	if sum_of_given_benefit and flt(sum_of_given_benefit[0].total_amount) > 0:
		total_given_benefit_amount = sum_of_given_benefit[0].total_amount
	return total_given_benefit_amount


def get_holiday_dates_for_employee(employee, start_date, end_date):
	"""return a list of holiday dates for the given employee between start_date and end_date"""
	# return only date
	holidays = get_holidays_for_employee(employee, start_date, end_date)

	return [cstr(h.holiday_date) for h in holidays]


def get_holidays_for_employee(employee, start_date, end_date, raise_exception=True, only_non_weekly=False):
	"""Get Holidays for a given employee

	`employee` (str)
	`start_date` (str or datetime)
	`end_date` (str or datetime)
	`raise_exception` (bool)
	`only_non_weekly` (bool)

	return: list of dicts with `holiday_date` and `description`
	"""
	holiday_list = get_holiday_list_for_employee(employee, raise_exception=raise_exception)

	if not holiday_list:
		return []

	filters = {"parent": holiday_list, "holiday_date": ("between", [start_date, end_date])}

	if only_non_weekly:
		filters["weekly_off"] = False

	holidays = frappe.get_all(
		"Holiday", fields=["description", "holiday_date"], filters=filters, order_by="holiday_date"
	)

	return holidays


@erpnext.allow_regional
def calculate_annual_eligible_hra_exemption(doc):
	# Don't delete this method, used for localization
	# Indian HRA Exemption Calculation
	return {}


@erpnext.allow_regional
def calculate_hra_exemption_for_period(doc):
	# Don't delete this method, used for localization
	# Indian HRA Exemption Calculation
	return {}


def get_previous_claimed_amount(employee, payroll_period, non_pro_rata=False, component=False):
	total_claimed_amount = 0
	query = """
	select sum(claimed_amount) as 'total_amount'
	from `tabEmployee Benefit Claim`
	where employee=%(employee)s
	and docstatus = 1
	and (claim_date between %(start_date)s and %(end_date)s)
	"""
	if non_pro_rata:
		query += "and pay_against_benefit_claim = 1"
	if component:
		query += "and earning_component = %(component)s"

	sum_of_claimed_amount = frappe.db.sql(
		query,
		{
			"employee": employee,
			"start_date": payroll_period.start_date,
			"end_date": payroll_period.end_date,
			"component": component,
		},
		as_dict=True,
	)
	if sum_of_claimed_amount and flt(sum_of_claimed_amount[0].total_amount) > 0:
		total_claimed_amount = sum_of_claimed_amount[0].total_amount
	return total_claimed_amount


def share_doc_with_approver(doc, user):
	if not user:
		return

	# if approver does not have permissions, share
	if not frappe.has_permission(doc=doc, ptype="submit", user=user):
		frappe.share.add_docshare(
			doc.doctype, doc.name, user, submit=1, flags={"ignore_share_permission": True}
		)

		frappe.msgprint(_("Shared with the user {0} with 'submit' permisions").format(user, alert=True))

	# remove shared doc if approver changes
	doc_before_save = doc.get_doc_before_save()
	if doc_before_save:
		approvers = {
			"Leave Application": "leave_approver",
			"Expense Claim": "expense_approver",
			"Shift Request": "approver",
		}

		approver = approvers.get(doc.doctype)
		if doc_before_save.get(approver) != doc.get(approver):
			frappe.share.remove(doc.doctype, doc.name, doc_before_save.get(approver))


def validate_active_employee(employee, method=None):
	if isinstance(employee, dict | Document):
		employee = employee.get("employee")

	if employee and frappe.db.get_value("Employee", employee, "status") == "Inactive":
		frappe.throw(
			_("Transactions cannot be created for an Inactive Employee {0}.").format(
				get_link_to_form("Employee", employee)
			),
			InactiveEmployeeStatusError,
		)


def validate_loan_repay_from_salary(doc, method=None):
	if doc.applicant_type == "Employee" and doc.repay_from_salary:
		from hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment import (
			get_employee_currency,
		)

		if not doc.applicant:
			frappe.throw(_("Please select an Applicant"))

		if not doc.company:
			frappe.throw(_("Please select a Company"))

		employee_currency = get_employee_currency(doc.applicant)
		company_currency = erpnext.get_company_currency(doc.company)
		if employee_currency != company_currency:
			frappe.throw(
				_(
					"Loan cannot be repayed from salary for Employee {0} because salary is processed in currency {1}"
				).format(doc.applicant, employee_currency)
			)

	if not doc.is_term_loan and doc.repay_from_salary:
		frappe.throw(_("Repay From Salary can be selected only for term loans"))


def get_matching_queries(
	bank_account,
	company,
	transaction,
	document_types,
	exact_match,
	account_from_to=None,
	from_date=None,
	to_date=None,
	filter_by_reference_date=None,
	from_reference_date=None,
	to_reference_date=None,
	common_filters=None,
):
	"""Returns matching queries for Bank Reconciliation"""
	queries = []
	if transaction.withdrawal > 0:
		if "expense_claim" in document_types:
			ec_amount_matching = get_ec_matching_query(
				bank_account, company, exact_match, from_date, to_date, common_filters
			)
			queries.extend([ec_amount_matching])

	return queries


def get_ec_matching_query(
	bank_account, company, exact_match, from_date=None, to_date=None, common_filters=None
):
	# get matching Expense Claim query
	filters = []
	ec = qb.DocType("Expense Claim")

	mode_of_payments = [
		x["parent"]
		for x in frappe.db.get_all(
			"Mode of Payment Account", filters={"default_account": bank_account}, fields=["parent"]
		)
	]
	company_currency = get_company_currency(company)

	filters.append(ec.docstatus == 1)
	filters.append(ec.is_paid == 1)
	filters.append(ec.clearance_date.isnull())
	if mode_of_payments:
		filters.append(ec.mode_of_payment.isin(mode_of_payments))

	if common_filters:
		ref_rank = frappe.qb.terms.Case().when(ec.employee == common_filters.party, 1).else_(0) + 1

		if exact_match:
			filters.append(ec.total_sanctioned_amount == common_filters.amount)
		else:
			filters.append(ec.total_sanctioned_amount.gt(common_filters.amount))
	else:
		ref_rank = ConstantColumn(1)

	if from_date and to_date:
		filters.append(ec.posting_date[from_date:to_date])

	ec_query = (
		qb.from_(ec)
		.select(
			ref_rank.as_("rank"),
			ec.name,
			ec.total_sanctioned_amount.as_("paid_amount"),
			ConstantColumn("").as_("reference_no"),
			ConstantColumn("").as_("reference_date"),
			ec.employee.as_("party"),
			ConstantColumn("Employee").as_("party_type"),
			ec.posting_date,
			ConstantColumn(company_currency).as_("currency"),
		)
		.where(Criterion.all(filters))
	)

	if from_date and to_date:
		ec_query = ec_query.orderby(ec.posting_date)

	return ec_query


def validate_bulk_tool_fields(
	self, fields: list, employees: list, from_date: str | None = None, to_date: str | None = None
) -> None:
	for d in fields:
		if not self.get(d):
			frappe.throw(_("{0} is required").format(self.meta.get_label(d)), title=_("Missing Field"))
	if self.get(from_date) and self.get(to_date):
		self.validate_from_to_dates(from_date, to_date)
	if not employees:
		frappe.throw(
			_("Please select at least one employee to perform this action."),
			title=_("No Employees Selected"),
		)


def notify_bulk_action_status(doctype: str, failure: list, success: list) -> None:
	frappe.clear_messages()

	msg = ""
	title = ""
	if failure:
		msg += _("Failed to create/submit {0} for employees:").format(doctype)
		msg += " " + comma_and(failure, False) + "<hr>"
		msg += (
			_("Check {0} for more details")
			.format("<a href='/app/List/Error Log?reference_doctype={0}'>{1}</a>")
			.format(doctype, _("Error Log"))
		)

		if success:
			title = _("Partial Success")
			msg += "<hr>"
		else:
			title = _("Creation Failed")
	else:
		title = _("Success")

	if success:
		msg += _("Successfully created {0} for employees:").format(doctype)
		msg += " " + comma_and(success, False)

	if failure:
		indicator = "orange" if success else "red"
	else:
		indicator = "green"

	frappe.msgprint(
		msg,
		indicator=indicator,
		title=title,
		is_minimizable=True,
	)


@frappe.whitelist()
def set_geolocation_from_coordinates(doc):
	if not frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking"):
		return

	if not (doc.latitude and doc.longitude):
		return

	doc.geolocation = frappe.json.dumps(
		{
			"type": "FeatureCollection",
			"features": [
				{
					"type": "Feature",
					"properties": {},
					# geojson needs coordinates in reverse order: long, lat instead of lat, long
					"geometry": {"type": "Point", "coordinates": [doc.longitude, doc.latitude]},
				}
			],
		}
	)


def get_distance_between_coordinates(lat1, long1, lat2, long2):
	from math import asin, cos, pi, sqrt

	r = 6371
	p = pi / 180

	a = 0.5 - cos((lat2 - lat1) * p) / 2 + cos(lat1 * p) * cos(lat2 * p) * (1 - cos((long2 - long1) * p)) / 2
	return 2 * r * asin(sqrt(a)) * 1000


def check_app_permission():
	"""Check if user has permission to access the app (for showing the app on app screen)"""
	if frappe.session.user == "Administrator":
		return True

	if frappe.has_permission("Employee", ptype="read"):
		return True

	return False


def get_exact_month_diff(string_ed_date: DateTimeLikeObject, string_st_date: DateTimeLikeObject) -> int:
	"""Return the difference between given two dates in months."""
	ed_date = getdate(string_ed_date)
	st_date = getdate(string_st_date)
	diff = (ed_date.year - st_date.year) * 12 + ed_date.month - st_date.month

	# count the last month only if end date's day > start date's day
	# to handle cases like 16th Jul 2024 - 15th Jul 2025
	# where framework's month_diff will calculate diff as 13 months
	if ed_date.day > st_date.day:
		diff += 1
	return diff


def get_mo_leave_management_rules():
	"""Return MO leave rules + toggles from the source-of-truth Single DocType."""
	defaults = frappe._dict(
		{
			"auto_allocate_monthly_leaves": 0,
			"auto_allocate_year_plus_leaves": 1,
			"vacation_eligible_after_years": 5,
			"monthly_sick_leave_days": 6.0,
			"monthly_local_leave_days": 6.0,
			# Year+ leave defaults
			"year_plus_special_leave_days": 0.0,
			"year_plus_wedding_leave_days": 6.0,
			"year_plus_compassionate_leave_days": 3.0,
			"year_plus_sick_leave_days": 15.0,
			"year_plus_local_leave_days": 22.0,
			"year_plus_maternity_leave_days": 112.0,
			"year_plus_paternity_leave_days": 28.0,
			"year_plus_vacation_leave_days": 30.0,
			# First 6 months defaults
			"first6_injury_leave_days": 14.0,
			"first6_training_leave_days": 10.0,
		}
	)

	if not frappe.db.table_exists("MO Leave Management System"):
		return defaults

	try:
		doc = frappe.get_single("MO Leave Management System")
		out = frappe._dict({**defaults})
		# Update with values from doc if they exist
		for k in defaults:
			if doc.get(k) is not None:
				out[k] = doc.get(k)
		return out
	except Exception:
		return defaults


def allocate_mo_threshold_leaves(employee=None, target_date=None):
	"""
	Daily threshold allocator (idempotent).
	Runs daily (weekdays only) to automatically allocate leaves for employees who cross tenure thresholds.

	- If employee crosses 6 months (and is < 12 months): allocate Monthly Sick Leave and Monthly Local Leave
	- If employee crosses 12 months: allocate yearly leaves (12+ leaves)
	"""
	if not target_date:
		target_date = getdate()

	# Weekdays only (Mon-Fri). Python weekday: Mon=0 ... Sun=6
	if getdate(target_date).weekday() >= 5:
		return {"skipped": "weekend"}

	rules = get_mo_leave_management_rules()
	# Automatic allocation - no toggle required, always enabled

	Employee = frappe.qb.DocType("Employee")
	MOAssignment = frappe.qb.DocType("MO Leave Policy Assignment")

	query = (
		frappe.qb.from_(Employee)
		.join(MOAssignment)
		.on(Employee.name == MOAssignment.employee)
		.select(
			Employee.name,
			Employee.date_of_joining,
			Employee.gender,
			MOAssignment.name.as_("assignment"),
			MOAssignment.effective_from,
			MOAssignment.effective_to,
		)
		.where(
			(Employee.status == "Active")
			& (MOAssignment.docstatus == 1)
			& (MOAssignment.effective_from <= target_date)
			& (MOAssignment.effective_to >= target_date)
		)
	)

	if employee:
		if isinstance(employee, list):
			query = query.where(Employee.name.isin(employee))
		else:
			query = query.where(Employee.name == employee)

	rows = query.run(as_dict=True)

	success = []
	failure = []

	for r in rows:
		try:
			doj = getdate(r.date_of_joining)
			tenure_months = get_exact_month_diff(target_date, doj)

			# 6-12 months: allocate monthly leaves (automatic, no toggle required)
			# This handles employees who cross the 6-month threshold after assignment creation
			# Include exactly 12 months in the monthly leaves range
			# Monthly leaves are only allocated if employee has NOT been absent for 6 consecutive months
			if 6 <= tenure_months <= 12:
				try:
					# Check if employee already has monthly leaves for this period
					# If not, allocate them (handles case where employee crossed threshold after assignment)
					# Pass target_date to check absence for 6 consecutive months
					_allocate_mo_monthly_leaves_if_missing(
						employee=r.name,
						assignment_name=r.assignment,
						from_date=r.effective_from,
						to_date=r.effective_to,
						monthly_sick_days=flt(rules.monthly_sick_leave_days),
						monthly_local_days=flt(rules.monthly_local_leave_days),
						check_date=target_date,
					)
				except Exception as e:
					# Log specific error for monthly leaves with more context
					frappe.log_error(
						f"Failed to allocate monthly leaves for {r.name} (tenure: {tenure_months} months, DOJ: {doj}, Assignment: {r.assignment}, Period: {r.effective_from} to {r.effective_to}): {str(e)}",
						"MO Daily Allocator - Monthly Leaves Error"
					)
					raise

			# 12+ months: allocate yearly leaves (automatic, no toggle required)
			if tenure_months >= 12:
				try:
					_allocate_mo_yearly_leaves_if_missing(
						employee=r.name,
						assignment_name=r.assignment,
						from_date=r.effective_from,
						to_date=r.effective_to,
						date_of_joining=doj,
						gender=r.gender,
						rules=rules,
					)
				except Exception as e:
					# Log specific error for yearly leaves
					frappe.log_error(
						f"Failed to allocate yearly leaves for {r.name} (tenure: {tenure_months} months, Assignment: {r.assignment}): {str(e)}",
						"MO Daily Allocator - Yearly Leaves Error"
					)
					raise

			success.append(r.name)
		except Exception as e:
			frappe.log_error(
				f"MO daily threshold allocation failed for {r.name}: {str(e)}",
				"MO Daily Allocator Error",
			)
			failure.append({"employee": r.name, "error": str(e)})

	return {"success": success, "failure": failure}


def _check_no_absence_for_6_consecutive_months(employee, check_date):
	"""
	Check if employee has NOT been absent for 6 consecutive months ending at check_date.
	Returns True if employee has NOT been absent (eligible for monthly leaves), False otherwise.
	
	Absence is defined as:
	- Leave Applications (approved) of any type
	- Attendance marked as "Absent" or "On Leave"
	"""
	# Calculate the 6-month period (6 months back from check_date)
	six_months_ago = add_months(check_date, -6)
	period_start = getdate(f"{six_months_ago.year}-{six_months_ago.month:02d}-01")
	period_end = getdate(check_date)
	
	# Check for Leave Applications (any approved leave counts as absence)
	LeaveApplication = frappe.qb.DocType("Leave Application")
	leave_applications = (
		frappe.qb.from_(LeaveApplication)
		.select(LeaveApplication.name)
		.where(
			(LeaveApplication.employee == employee)
			& (LeaveApplication.status == "Approved")
			& (LeaveApplication.docstatus == 1)
			& (
				# Leave overlaps with the 6-month period
				(
					(LeaveApplication.from_date <= period_end)
					& (LeaveApplication.to_date >= period_start)
				)
			)
		)
	).run()
	
	if leave_applications:
		# Employee has taken leave in the 6-month period
		return False
	
	# Check for Attendance marked as "Absent" or "On Leave"
	Attendance = frappe.qb.DocType("Attendance")
	absent_records = (
		frappe.qb.from_(Attendance)
		.select(Attendance.name)
		.where(
			(Attendance.employee == employee)
			& (Attendance.attendance_date >= period_start)
			& (Attendance.attendance_date <= period_end)
			& (Attendance.status.isin(["Absent", "On Leave"]))
			& (Attendance.docstatus == 1)
		)
	).run()
	
	if absent_records:
		# Employee has been marked absent in the 6-month period
		return False
	
	# No absences found - employee is eligible
	return True


def _allocate_mo_monthly_leaves_if_missing(
	employee, assignment_name, from_date, to_date, monthly_sick_days=6.0, monthly_local_days=6.0, check_date=None
):
	"""
	Allocate Monthly Sick/Local leaves if they don't already exist (idempotent).
	Only allocates if employee has NOT been absent for 6 consecutive months.
	"""
	LeaveAllocation = frappe.qb.DocType("Leave Allocation")
	
	# Use check_date if provided, otherwise use current date
	if not check_date:
		check_date = getdate()
	else:
		check_date = getdate(check_date)

	def _exists(leave_type):
		"""Check if allocation exists for this leave type in the assignment period."""
		result = (
			frappe.qb.from_(LeaveAllocation)
			.select(LeaveAllocation.name)
			.where(
				(LeaveAllocation.employee == employee)
				& (LeaveAllocation.leave_type == leave_type)
				& (LeaveAllocation.from_date == from_date)
				& (LeaveAllocation.to_date == to_date)
				& (LeaveAllocation.docstatus == 1)
			)
		).run()
		exists = len(result) > 0
		# Allocation already exists, skip (idempotent behavior)
		return exists

	# Check if employee has been absent for 6 consecutive months
	# Monthly leaves are only allocated if employee has NOT been absent
	if not _check_no_absence_for_6_consecutive_months(employee, check_date):
		# Employee has been absent - skip allocation
		# Log this for tracking (using log_error with info level, as log_info doesn't exist)
		frappe.log_error(
			f"Monthly leaves not allocated for {employee}: employee has been absent in the last 6 consecutive months (checked up to {check_date})",
			"MO Daily Allocator - Monthly Leaves Eligibility"
		)
		return

	# Monthly Sick Leave
	if not _exists("Monthly Sick Leave") and monthly_sick_days > 0:
		try:
			_create_leave_allocation_simple(
				employee=employee,
				leave_type="Monthly Sick Leave",
				from_date=from_date,
				to_date=to_date,
				new_leaves_allocated=monthly_sick_days,
				description=f"Auto-allocated via daily scheduler (6-12 months, Assignment: {assignment_name})",
			)
		except Exception as e:
			frappe.log_error(
				f"Failed to allocate Monthly Sick Leave for {employee} (Assignment: {assignment_name}): {str(e)}",
				"MO Daily Allocator - Monthly Sick Leave Error"
			)
			raise

	# Monthly Local Leave
	if not _exists("Monthly Local Leave") and monthly_local_days > 0:
		try:
			_create_leave_allocation_simple(
				employee=employee,
				leave_type="Monthly Local Leave",
				from_date=from_date,
				to_date=to_date,
				new_leaves_allocated=monthly_local_days,
				description=f"Auto-allocated via daily scheduler (6-12 months, Assignment: {assignment_name})",
			)
		except Exception as e:
			frappe.log_error(
				f"Failed to allocate Monthly Local Leave for {employee} (Assignment: {assignment_name}): {str(e)}",
				"MO Daily Allocator - Monthly Local Leave Error"
			)
			raise


def _allocate_mo_yearly_leaves_if_missing(employee, assignment_name, from_date, to_date, date_of_joining, gender, rules):
	"""Allocate yearly leaves (12+) if they don't already exist (idempotent)."""
	from hrms.hr.doctype.mo_leave_policy_assignment.mo_leave_policy_assignment import (
		MOLeavePolicyAssignment,
	)

	LeaveAllocation = frappe.qb.DocType("Leave Allocation")

	def _exists(leave_type):
		"""Check if allocation exists for this leave type in the assignment period (only submitted)."""
		result = (
			frappe.qb.from_(LeaveAllocation)
			.select(LeaveAllocation.name)
			.where(
				(LeaveAllocation.employee == employee)
				& (LeaveAllocation.leave_type == leave_type)
				& (LeaveAllocation.from_date == from_date)
				& (LeaveAllocation.to_date == to_date)
				& (LeaveAllocation.docstatus == 1)  # Only check submitted allocations
			)
		).run()
		return len(result) > 0

	# Calculate tenure for proration
	tenure_months = MOLeavePolicyAssignment.calculate_tenure_months_static(date_of_joining, from_date)
	tenure_years = flt(tenure_months) / 12.0

	# Get gender-based allocations
	# Gender is a Link field, so we need to get the gender name from the Gender doctype
	gender_lower = ""
	if gender:
		if frappe.db.exists("Gender", gender):
			gender_name = frappe.db.get_value("Gender", gender, "gender")
			if gender_name:
				gender_lower = gender_name.lower()

	# Custom rounding function for prorated leaves (0.5 increments)
	def _round_to_half(value):
		"""
		Round to 0.5 increments with custom rules:
		- 0 < x < 0.25 → 0
		- 0.25 ≤ x < 0.5 → 0.5
		- 0.5 ≤ x < 0.75 → 0.5
		- 0.75 ≤ x < 1.0 → 1
		"""
		import math
		integer_part = math.floor(value)
		decimal_part = value - integer_part
		
		if decimal_part == 0:
			return flt(integer_part)
		elif 0 < decimal_part < 0.25:
			return flt(integer_part)
		elif 0.25 <= decimal_part < 0.5:
			return flt(integer_part + 0.5)
		elif 0.5 <= decimal_part < 0.75:
			return flt(integer_part + 0.5)
		elif 0.75 <= decimal_part < 1.0:
			return flt(integer_part + 1.0)
		else:
			# Should not happen, but fallback to standard rounding
			return flt(round(value, 1))
	
	# Calculate prorated leaves using formula: (Annual Leave ÷ 12) × Remaining Months
	def _get_prorated_leave(annual_allocation):
		"""
		Prorate annual leave based on remaining months from one-year anniversary to period end.
		Formula: Prorated Leave = (Annual Leave ÷ 12) × Remaining Months
		Result is rounded to 0.5 increments using custom rounding rules.
		"""
		doj = getdate(date_of_joining)
		period_from = getdate(from_date)
		period_to = getdate(to_date)
		
		# Calculate one-year anniversary date
		one_year_anniversary = getdate(f"{doj.year + 1}-{doj.month:02d}-{doj.day:02d}")
		
		# If anniversary is after period start, calculate remaining months
		if one_year_anniversary > period_from:
			# Calculate remaining months from anniversary to period end
			from dateutil.relativedelta import relativedelta
			from frappe.utils import date_diff
			
			# Calculate months between anniversary and period end
			delta = relativedelta(period_to, one_year_anniversary)
			remaining_months = delta.years * 12 + delta.months
			
			# Add fractional month if there are remaining days
			if delta.days > 0:
				# Calculate days in the month containing the anniversary date
				# Get the last day of the month containing the anniversary
				if one_year_anniversary.month == 12:
					last_day_of_month = getdate(f"{one_year_anniversary.year + 1}-01-01") - relativedelta(days=1)
				else:
					last_day_of_month = getdate(f"{one_year_anniversary.year}-{one_year_anniversary.month + 1:02d}-01") - relativedelta(days=1)
				days_in_anniversary_month = last_day_of_month.day
				days_from_anniversary_to_month_end = days_in_anniversary_month - one_year_anniversary.day + 1
				
				# If we're still in the same month, use days in that month
				if one_year_anniversary.month == period_to.month and one_year_anniversary.year == period_to.year:
					days_in_month = days_in_anniversary_month
				else:
					# Use days in the month of the period end
					if period_to.month == 12:
						last_day_of_end_month = getdate(f"{period_to.year + 1}-01-01") - relativedelta(days=1)
					else:
						last_day_of_end_month = getdate(f"{period_to.year}-{period_to.month + 1:02d}-01") - relativedelta(days=1)
					days_in_month = last_day_of_end_month.day
				
				# Add fractional month
				remaining_months += flt(delta.days) / flt(days_in_month)
			
			# Apply formula: (Annual Leave ÷ 12) × Remaining Months
			prorated = (flt(annual_allocation) / 12.0) * remaining_months
			# Apply custom rounding to 0.5 increments
			return _round_to_half(prorated)
		
		# If anniversary is before or on period start, employee gets full allocation
		return flt(annual_allocation)

	# Allocate yearly leaves if missing
	# According to daily scheduler rules for 12+ employees:
	# - Special Leave: 0 (always allocated even if 0)
	# - Wedding Leave: receive full amount for the year
	# - Compassionate Leave: receive full amount for the year
	# - Local Leave: prorated for the year
	# - Paternity Leave: receive full amount for the year
	# - Maternity Leave: receive full amount for the year
	# - Sick Leave: prorated for the year
	# - Vacation Leave: receive full amount only once (after 5 years)
	
	yearly_leaves = {
		"Special Leave": flt(rules.year_plus_special_leave_days or 0),  # Usually 0, but allocate it
		"Wedding Leave": flt(rules.year_plus_wedding_leave_days or 0),  # Full amount for the year
		"Compassionate Leave": flt(rules.year_plus_compassionate_leave_days or 0),  # Full amount for the year
		"Sick Leave": _get_prorated_leave(rules.year_plus_sick_leave_days or 0),  # Prorated for the year
		"Local Leave": _get_prorated_leave(rules.year_plus_local_leave_days or 0),  # Prorated for the year
	}

	# Gender-based leaves (full amount for the year)
	if gender_lower in ["female", "f"]:
		yearly_leaves["Maternity Leave"] = flt(rules.year_plus_maternity_leave_days)  # Full amount for the year
	if gender_lower in ["male", "m"]:
		yearly_leaves["Paternity Leave"] = flt(rules.year_plus_paternity_leave_days)  # Full amount for the year

	# Vacation Leave: only after 5 years, receive full amount only once
	if tenure_years >= 5:
		# Check if employee already received Vacation Leave in a previous year
		has_previous_vacation = frappe.db.exists(
			"Leave Allocation",
			{
				"employee": employee,
				"leave_type": "Vacation Leave",
				"docstatus": 1,
				"from_date": ("<", from_date),
			},
		)
		# Only allocate if they haven't received it before
		if not has_previous_vacation:
			yearly_leaves["Vacation Leave"] = flt(rules.year_plus_vacation_leave_days)  # Full amount, only once

	# Create allocations for missing leaves
	# Only allocate if they don't already exist (idempotent)
	for leave_type, allocation_amount in yearly_leaves.items():
		# Skip 0 allocations (framework doesn't allow 0 allocations)
		if allocation_amount <= 0:
			continue
		
		# Check if allocation already exists
		if _exists(leave_type):
			continue
		
		# Check if it's LWP (shouldn't allocate)
		is_lwp = frappe.db.get_value("Leave Type", leave_type, "is_lwp")
		if is_lwp:
			# Skip LWP leaves
			continue
		
		# Create the allocation
		try:
			_create_leave_allocation_simple(
				employee=employee,
				leave_type=leave_type,
				from_date=from_date,
				to_date=to_date,
				new_leaves_allocated=allocation_amount,
				description=f"Auto-allocated via daily scheduler (12+ months, Assignment: {assignment_name})",
			)
		except Exception as e:
			frappe.log_error(
				f"Failed to allocate {leave_type} for {employee} (Assignment: {assignment_name}, Amount: {allocation_amount}): {str(e)}",
				"MO Daily Allocator - Yearly Leave Allocation Error"
			)
			raise


def _create_leave_allocation_simple(employee, leave_type, from_date, to_date, new_leaves_allocated, description):
	"""Helper to create a Leave Allocation (submitted) with minimal fields."""
	try:
		allocation = frappe.get_doc(
			{
				"doctype": "Leave Allocation",
				"employee": employee,
				"leave_type": leave_type,
				"from_date": from_date,
				"to_date": to_date,
				"new_leaves_allocated": new_leaves_allocated,
				"description": description,
				"carry_forward": 0,
			}
		)
		allocation.save(ignore_permissions=True)
		allocation.submit()
	except Exception as e:
		frappe.log_error(
			f"Failed to allocate {leave_type} for employee {employee}: {str(e)}",
			"MO Leave Allocation Error",
		)


def _process_bank_leaves(employee, old_assignment, period_end_date):
	"""Process bank leave transfers: unused leaves to bank leaves"""
	from frappe.utils import get_first_day, get_last_day

	# Get unused balances
	LeaveAllocation = frappe.qb.DocType("Leave Allocation")
	LeaveLedgerEntry = frappe.qb.DocType("Leave Ledger Entry")

	# Get unused Monthly Sick Leave
	monthly_sick_balance = _get_unused_leave_balance(employee, "Monthly Sick Leave", period_end_date)
	# Get unused Sick Leave
	sick_leave_balance = _get_unused_leave_balance(employee, "Sick Leave", period_end_date)

	# Transfer to Bank Sick Leave (accumulates)
	if monthly_sick_balance > 0 or sick_leave_balance > 0:
		bank_sick_total = monthly_sick_balance + sick_leave_balance
		# Get existing Bank Sick Leave balance
		existing_bank_sick = _get_leave_balance(employee, "Bank Sick Leave")
		new_bank_sick = existing_bank_sick + bank_sick_total

		# Create allocation for Bank Sick Leave
		next_period_start = add_months(period_end_date, 1)
		next_period_end = add_months(next_period_start, 12)

		_create_bank_leave_allocation(
			employee, "Bank Sick Leave", new_bank_sick, next_period_start, next_period_end
		)

	# Get unused Local Leave and Monthly Local Leave
	local_leave_balance = _get_unused_leave_balance(employee, "Local Leave", period_end_date)
	monthly_local_balance = _get_unused_leave_balance(employee, "Monthly Local Leave", period_end_date)

	# Bank Local Leave resets, then takes unused from previous year
	bank_local_total = local_leave_balance + monthly_local_balance

	if bank_local_total > 0:
		next_period_start = add_months(period_end_date, 1)
		next_period_end = add_months(next_period_start, 12)

		_create_bank_leave_allocation(
			employee, "Bank Local Leave", bank_local_total, next_period_start, next_period_end
		)


def allocate_mo_daily_weekday_allocator():
	"""
	Daily scheduler entrypoint (runs on weekdays only).
	Automatically allocates missing leaves for employees who crossed tenure thresholds:
	- 6-12 months: Monthly Sick Leave and Monthly Local Leave
	- 12+ months: Yearly leaves (Sick Leave, Local Leave, Wedding, Compassionate, etc.)
	"""
	return allocate_mo_threshold_leaves()


def _get_unused_leave_balance(employee, leave_type, as_of_date):
	"""Get unused leave balance for a specific leave type as of a specific date"""
	from frappe.query_builder.functions import Sum
	
	LeaveAllocation = frappe.qb.DocType("Leave Allocation")
	LeaveLedgerEntry = frappe.qb.DocType("Leave Ledger Entry")

	# Get total allocated (sum of all allocations that were active at as_of_date)
	total_allocated = (
		frappe.qb.from_(LeaveAllocation)
		.select(Sum(LeaveAllocation.new_leaves_allocated))
		.where(
			(LeaveAllocation.employee == employee)
			& (LeaveAllocation.leave_type == leave_type)
			& (LeaveAllocation.from_date <= as_of_date)
			& (LeaveAllocation.to_date >= as_of_date)
			& (LeaveAllocation.docstatus == 1)
		)
	).run()[0][0] or 0

	# Get total used (sum of all ledger entries up to as_of_date)
	# Note: Leave ledger entries have negative values for usage
	# Filter by to_date <= as_of_date to get all usage up to that date
	total_used = (
		frappe.qb.from_(LeaveLedgerEntry)
		.select(Sum(LeaveLedgerEntry.leaves))
		.where(
			(LeaveLedgerEntry.employee == employee)
			& (LeaveLedgerEntry.leave_type == leave_type)
			& (LeaveLedgerEntry.to_date <= as_of_date)
			& (LeaveLedgerEntry.is_expired == 0)
			& (LeaveLedgerEntry.docstatus == 1)
		)
	).run()[0][0] or 0

	# Unused = allocated - used (used is negative, so we add it)
	# total_used will be negative (e.g., -5 for 5 days used)
	unused = flt(total_allocated) + flt(total_used)
	return max(0, unused)


def _get_leave_balance(employee, leave_type):
	"""Get current leave balance"""
	from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

	return get_leave_balance_on(employee, leave_type, getdate()) or 0


def _create_bank_leave_allocation(employee, leave_type, new_leaves, from_date, to_date, description=None):
	"""Create bank leave allocation"""
	try:
		if description is None:
			description = f"Bank leave allocation from yearly reassignment"
		
		allocation = frappe.get_doc(
			{
				"doctype": "Leave Allocation",
				"employee": employee,
				"leave_type": leave_type,
				"from_date": from_date,
				"to_date": to_date,
				"new_leaves_allocated": new_leaves,
				"description": description,
				"carry_forward": 0,
			}
		)
		allocation.save(ignore_permissions=True)
		allocation.submit()
	except Exception as e:
		frappe.log_error(
			f"Failed to create bank leave allocation for {employee}, {leave_type}: {str(e)}",
			"MO Bank Leave Allocation Error",
		)


def _create_new_mo_assignment(employee, old_period_end):
	"""Create new MO Leave Policy Assignment for next period"""
	from frappe.utils import add_months

	date_of_joining = frappe.db.get_value("Employee", employee, "date_of_joining")
	if not date_of_joining:
		frappe.log_error(
			f"Employee {employee} does not have date of joining",
			"MO Assignment Creation Error",
		)
		return

	# Check if new assignment already exists
	new_from = add_months(old_period_end, 1)
	existing = frappe.db.exists(
		"MO Leave Policy Assignment",
		{
			"employee": employee,
			"effective_from": new_from,
			"docstatus": ("!=", 2),
		},
	)
	if existing:
		return  # Assignment already exists

	new_to = add_months(new_from, 12)

	try:
		assignment = frappe.get_doc(
			{
				"doctype": "MO Leave Policy Assignment",
				"employee": employee,
				"assignment_based_on": "Joining Date",
				"effective_from": new_from,
				"effective_to": new_to,
			}
		)
		assignment.save(ignore_permissions=True)
		assignment.submit()
	except Exception as e:
		frappe.log_error(
			f"Failed to create new MO assignment for employee {employee}: {str(e)}",
			"MO Assignment Creation Error",
		)

    
