# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Extract, Sum
from frappe.utils import cint, cstr, getdate, get_last_day, add_days
from frappe.utils.nestedset import get_descendants_of
from hrms.hr.report.monthly_attendance_sheet.monthly_attendance_sheet import get_employee_related_details
from hrms.hr.report.monthly_attendance_sheet.monthly_attendance_sheet import get_attendance_map
import calendar
from datetime import datetime, date, timedelta

Filters = frappe._dict

def execute(filters: dict | None = None):
    """Return columns and data for the report.

    This is the main entry point for the report. It accepts the filters as a
    dictionary and should return columns and data. It is called by the framework
    every time the report is refreshed or a filter is updated.
    """
    filters = frappe._dict(filters or {})

    if not (filters.from_date and filters.to_date):
        frappe.throw(_("Please select start and end date."))

    if not filters.company:
        frappe.throw(_("Please select company."))

    if filters.company:
        filters.companies = [filters.company]
        if filters.include_company_descendants:
            filters.companies.extend(get_descendants_of("Company", filters.company))

    columns = get_columns(filters)
    data = get_data(filters)

    if not data:
        frappe.msgprint(_("No employee records found for this criteria."), alert=True, indicator="orange")
        return columns, [], None, None

    # Return columns and data
    return columns, data


def get_columns(filters: Filters) -> list[dict]:
    columns = [
        {
            "label": _("Date"),
            "fieldname": "date",
            "fieldtype": "Date",
            "width": 150,
        },
        {
            "label": _("Employee Name"),
            "fieldname": "employee_name",
            "fieldtype": "Data",
            "width": 350,
        },
        {
            "label": _("Employee ID"),
            "fieldname": "employee",
            "fieldtype": "Link",
            "options": "Employee",
            "width": 200,
        },
        {
            "label": _("Status"),
            "fieldname": "status",
            "fieldtype": "Data",
            "width": 80,
        },
        {
            "label": _("Shift"),
            "fieldname": "shift",
            "fieldtype": "Data",
            "width": 100,
        },
        {
            "label": _("Time In"),
            "fieldname": "time_in",
            "fieldtype": "Time",
            "width": 100,
        },
        {
            "label": _("Time Out"),
            "fieldname": "time_out",
            "fieldtype": "Time",
            "width": 100,
        }
    ]
    
    return columns

def get_date_range(start_date, end_date) -> list[date]:
    """Generate all dates between start_date and end_date (inclusive)."""
    if isinstance(start_date, str):
        print("Converting start_date to date object")
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    print(start_date)
    delta = (end_date - start_date).days
    return [start_date + timedelta(days=i) for i in range(delta + 1)]

def get_employees_list(filters: Filters) -> list[dict]:
    """Get list of employees based on filters"""
    Employee = frappe.qb.DocType("Employee")
    
    query = (
        frappe.qb.from_(Employee)
        .select(
            Employee.name,
            Employee.employee_name,
            Employee.status,
            Employee.company
        )
        .where(
            (Employee.status == "Active")
            & (Employee.company.isin(filters.companies))
        )
    )
    
    if filters.employee:
        query = query.where(Employee.name == filters.employee)
    
    if filters.department:
        query = query.where(Employee.department == filters.department)
        
    query = query.orderby(Employee.employee_name)
    
    return query.run(as_dict=1)

def get_attendance_records(filters: Filters) -> dict:
    """Get attendance records and organize by employee and date"""
    Attendance = frappe.qb.DocType("Attendance")
    
    query = (
        frappe.qb.from_(Attendance)
        .select(
            Attendance.employee,
            Attendance.attendance_date,
            Attendance.status,
            Attendance.shift,
            Attendance.in_time,
            Attendance.out_time,
            Attendance.late_entry,
            Attendance.early_exit,
            Attendance.leave_type
        )
        .where(
            (Attendance.docstatus != 2)
            & (Attendance.company.isin(filters.companies))
            & (Attendance.attendance_date >= filters.from_date)
            & (Attendance.attendance_date <= filters.to_date)
        )
    )
    
    if filters.employee:
        query = query.where(Attendance.employee == filters.employee)
        
    attendance_records = query.run(as_dict=1)
    
    # Organize by employee and date for quick lookup
    attendance_map = {}
    for record in attendance_records:
        if record.employee not in attendance_map:
            attendance_map[record.employee] = {}
        attendance_map[record.employee][record.attendance_date] = record
    
    return attendance_map

def get_data(filters: Filters) -> list[dict]:
    """Get formatted data for the report including all dates for each employee"""
    
    # Get employees list
    employees = get_employees_list(filters)
    if not employees:
        return []
    
    # Get attendance records organized by employee and date
    attendance_map = get_attendance_records(filters)
    
    # Get all dates in the month
    dates = get_date_range(filters.from_date, filters.to_date)
    
    data = []
    
    for employee in employees:
        employee_id = employee.name
        employee_name = employee.employee_name
        
        for current_date in dates:
            # Check if attendance record exists for this employee and date
            attendance_record = None
            if employee_id in attendance_map and current_date in attendance_map[employee_id]:
                attendance_record = attendance_map[employee_id][current_date]
            
            # Create row for this employee and date
            if attendance_record:
                # Employee has attendance record
                row = {
                    "date": current_date,
                    "employee_name": employee_name,
                    "employee": employee_id,
                    "status": attendance_record.status or "",
                    "shift": attendance_record.shift or "",
                    "time_in": attendance_record.in_time.strftime("%H:%M") if attendance_record.in_time else "",
                    "time_out": attendance_record.out_time.strftime("%H:%M") if attendance_record.out_time else "",
                }
            else:
                # Employee has no attendance record - mark as Absent
                row = {
                    "date": current_date,
                    "employee_name": employee_name,
                    "employee": employee_id,
                    "status": "Absent",
                    "shift": "",
                    "time_in": "",
                    "time_out": "",
                }
            
            data.append(row)
    
    # Sort by employee name, then by date
    data.sort(key=lambda x: (x["employee_name"], x["date"]))
    
    return data