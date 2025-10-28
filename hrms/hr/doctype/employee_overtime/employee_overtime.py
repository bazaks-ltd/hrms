# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from datetime import datetime, timedelta

class EmployeeOvertime(Document):
	def validate(self):
			return # self.check_duplicate_overtime()
	
	def check_duplicate_overtime(self):
		# Find any record that overlaps the current one
		existing = frappe.db.sql("""
			SELECT name
			FROM `tabEmployee Overtime`
			WHERE employee = %(employee)s
			AND name != %(name)s
			AND workflow_state != 'Cancelled'
			AND (
				(from_time <= %(from_time)s AND to_time > %(from_time)s) OR
				(from_time < %(to_time)s AND to_time >= %(to_time)s) OR
				(from_time >= %(from_time)s AND to_time <= %(to_time)s)
			)
		""", {
			"employee": self.employee,
			"name": self.name or "",
			"from_time": self.from_time,
			"to_time": self.to_time
		}, as_dict=True)

		if existing:
			frappe.throw(
				_("Overtime record already exists for {0} overlapping {1} – {2}")
				.format(self.employee, self.from_time, self.to_time)
			)

@frappe.whitelist()
def get_overtime_approver(employee):
	emp_department = frappe.db.get_value("Employee", employee, ["department"])

	overtime_approver = frappe.db.get_value(
		"Department Approver",
		{"parent": emp_department, "parentfield": "overtime_approvers", "idx": 1},
		"approver",
	)
	return overtime_approver

@frappe.whitelist()
def migrate_overtime_dates():
    """
    API method to migrate Employee Overtime datetime fields
    """
    
    if not frappe.has_permission("Employee Overtime", "write"):
        frappe.throw("Insufficient permissions to run migration")
    
    try:
        # Get all Employee Overtime records that need migration
        records = frappe.db.sql("""
            SELECT name, date, from_time, to_time, employee
            FROM `tabEmployee Overtime`
            WHERE date IS NOT NULL
            AND from_time IS NOT NULL
            AND to_time IS NOT NULL
            AND DATE(from_time) != date  -- Only records where dates don't match
        """, as_dict=True)
        
        if not records:
            return {
                "status": "success",
                "message": "No records need migration. All dates are already correct!",
                "updated_count": 0
            }
        
        updated_count = 0
        errors = []
        
        for record in records:
            try:
                # Get the actual work date
                work_date = record.date
                
                # Extract time components from current datetime fields
                from_dt = frappe.utils.get_datetime(record.from_time)
                to_dt = frappe.utils.get_datetime(record.to_time)
                
                from_time = from_dt.time()
                to_time = to_dt.time()
                
                # Create new datetime with correct date
                new_from_datetime = datetime.combine(work_date, from_time)
                
                # Handle overnight shifts
                if to_time <= from_time:
                    # Overnight shift - to_time should be next day
                    next_day = work_date + timedelta(days=1)
                    new_to_datetime = datetime.combine(next_day, to_time)
                else:
                    # Same day shift
                    new_to_datetime = datetime.combine(work_date, to_time)
                
                # Update the record
                frappe.db.sql("""
                    UPDATE `tabEmployee Overtime`
                    SET from_time = %(from_time)s, to_time = %(to_time)s, modified = NOW()
                    WHERE name = %(name)s
                """, {
                    "from_time": new_from_datetime,
                    "to_time": new_to_datetime,
                    "name": record.name
                })
                
                updated_count += 1
                
            except Exception as e:
                errors.append(f"Error updating {record.name}: {str(e)}")
                continue
        
        frappe.db.commit()
        
        return {
            "status": "success",
            "message": f"Migration completed! Updated {updated_count} records.",
            "updated_count": updated_count,
            "errors": errors
        }
        
    except Exception as e:
        frappe.db.rollback()
        return {
            "status": "error",
            "message": f"Migration failed: {str(e)}"
        }
