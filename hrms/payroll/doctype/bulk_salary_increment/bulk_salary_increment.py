# bulk_salary_increment.py
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, formatdate
from frappe.model.naming import make_autoname

class BulkSalaryIncrement(Document):
    
    def autoname(self):
        """Generate human-readable name based on effective date"""
        if self.effective_from_date:
            date_str = formatdate(self.effective_from_date, "YYYY-MM")
            # Get next number in series for this month
            prefix = f"BSI-{date_str}"
            self.name = make_autoname(f"{prefix}-.#####", "", self)
        else:
            # Fallback if date not set - use current date
            self.name = make_autoname("BSI-.YYYY.-.MM.-.#####", "", self)
    
    def validate(self):
        self.validate_increment_value()
        # Ensure status is always Active
        if not self.status:
            self.status = "Active"
        if self.employees:
            self.calculate_increments()
    
    def validate_increment_value(self):
        """Ensure increment value is valid"""
        if flt(self.increment_value) <= 0:
            frappe.throw(_("Increment Value must be greater than zero"))
        
        if self.increment_type == "Percentage" and flt(self.increment_value) > 100:
            frappe.throw(_("Percentage increment cannot exceed 100%"))
    
    @frappe.whitelist()
    def get_employees(self):
        """Fetch employees based on filters"""
        # Always filter by Active status
        filters = {
            "status": "Active",
            "company": self.company
        }
        
        # Add optional filters
        if self.department:
            filters["department"] = self.department
        if self.designation:
            filters["designation"] = self.designation
        if self.branch:
            filters["branch"] = self.branch
        if self.grade:
            filters["grade"] = self.grade
        if self.employment_type:
            filters["employment_type"] = self.employment_type
        
        # Build query with basic salary filters
        Employee = frappe.qb.DocType("Employee")
        query = frappe.qb.from_(Employee).select(
            Employee.name,
            Employee.employee_name,
            Employee.department,
            Employee.designation,
            Employee.e_basic
        ).where(Employee.status == filters["status"]).where(Employee.company == filters["company"])
        
        # Add basic salary range filters
        if self.basic_salary_from:
            query = query.where(Employee.e_basic >= flt(self.basic_salary_from))
        if self.basic_salary_to:
            query = query.where(Employee.e_basic <= flt(self.basic_salary_to))
        
        # Add other filters
        if self.department:
            query = query.where(Employee.department == self.department)
        if self.designation:
            query = query.where(Employee.designation == self.designation)
        if self.branch:
            query = query.where(Employee.branch == self.branch)
        if self.grade:
            query = query.where(Employee.grade == self.grade)
        if self.employment_type:
            query = query.where(Employee.employment_type == self.employment_type)
        
        employees = query.orderby(Employee.employee_name).run(as_dict=True)
        
        # Clear existing employees
        self.set("employees", [])
        
        # Add filtered employees
        for emp in employees:
            current_salary = flt(emp.e_basic) or 0
            increment_details = self.calculate_increment_details(current_salary)
            
            self.append("employees", {
                "employee": emp.name,
                "employee_name": emp.employee_name,
                "department": emp.department,
                "designation": emp.designation,
                "current_basic_salary": current_salary,
                "increment_amount": increment_details["increment_amount"],
                "new_basic_salary": increment_details["new_basic_salary"],
                "increment_percentage": increment_details["increment_percentage"]
            })
        
        self.number_of_employees = len(self.employees)
        
        # Show dynamic message
        employee_count = len(self.employees)
        if employee_count > 0:
            increment_info = ""
            if self.increment_type == "Fixed Amount":
                increment_info = _("Fixed Amount: {0}").format(frappe.format_value(self.increment_value, {"fieldtype": "Currency"}))
            else:
                increment_info = _("Percentage: {0}%").format(frappe.format_value(self.increment_value, {"fieldtype": "Percent"}))
            
            frappe.msgprint(
                _("Found {0} employee(s) matching the criteria. {1}").format(employee_count, increment_info),
                indicator="blue"
            )
        else:
            frappe.msgprint(_("No employees found matching the selected criteria"), indicator="orange")
        
        return len(self.employees)
    
    def calculate_increment_details(self, current_salary):
        """Calculate increment amount and new salary"""
        current_salary = flt(current_salary)
        
        if self.increment_type == "Fixed Amount":
            increment_amount = flt(self.increment_value)
            new_salary = current_salary + increment_amount
            increment_percentage = (increment_amount / current_salary * 100) if current_salary else 0
        else:  # Percentage
            increment_percentage = flt(self.increment_value)
            increment_amount = current_salary * (increment_percentage / 100)
            new_salary = current_salary + increment_amount
        
        return {
            "increment_amount": increment_amount,
            "new_basic_salary": new_salary,
            "increment_percentage": increment_percentage
        }
    
    @frappe.whitelist()
    def calculate_increments(self):
        """Recalculate increments for all employees"""
        if not self.employees:
            return
        
        for emp in self.employees:
            current_salary = flt(emp.current_basic_salary) or 0
            if not current_salary:
                # Fetch from Employee if not set
                current_salary = frappe.db.get_value("Employee", emp.employee, "e_basic") or 0
                emp.current_basic_salary = current_salary
            
            increment_details = self.calculate_increment_details(current_salary)
            emp.increment_amount = increment_details["increment_amount"]
            emp.new_basic_salary = increment_details["new_basic_salary"]
            emp.increment_percentage = increment_details["increment_percentage"]
    
    def create_salary_history_records(self):
        """Create Salary History records for all employees - only called on submit"""
        if not self.employees:
            frappe.throw(_("No employees selected. Please get employees first."))
        
        # Ensure parent document is saved first
        if not self.name:
            self.save()
        
        created_records = []
        failed_employees = []
        employee_salary_history_map = {}
        
        for emp in self.employees:
            try:
                # Get employee's current basic salary
                current_salary = frappe.db.get_value("Employee", emp.employee, "e_basic") or 0
                
                # Create Salary History record
                salary_history = frappe.new_doc("Salary History")
                salary_history.employee = emp.employee
                salary_history.effective_from_date = self.effective_from_date
                salary_history.change_amount = flt(emp.increment_amount)
                salary_history.change_type = self.change_type
                salary_history.remarks = f"Bulk increment via {self.name}"
                # Set approver fields from bulk increment
                if self.approved_by:
                    salary_history.approved_by = self.approved_by
                if self.approval_date:
                    salary_history.approval_date = self.approval_date
                
                # Insert and submit
                salary_history.insert()
                salary_history.submit()
                
                created_records.append(salary_history.name)
                employee_salary_history_map[emp.employee] = salary_history.name
                
            except Exception as e:
                emp_name = emp.employee_name or emp.employee
                error_msg = f"{emp_name}: {str(e)}"
                failed_employees.append(error_msg)
                frappe.log_error(
                    title=f"Error creating salary history for {emp_name}",
                    message=f"Employee: {emp.employee}\nError: {str(e)}\nTraceback: {frappe.get_traceback()}"
                )
                continue
        
        # Update child table with salary_history references
        if self.name and employee_salary_history_map:
            for emp in self.employees:
                if emp.employee in employee_salary_history_map:
                    frappe.db.set_value(
                        "Bulk Salary Increment Employee",
                        emp.name,
                        "salary_history",
                        employee_salary_history_map[emp.employee]
                    )
        
        # Reload to refresh child table
        if self.name:
            self.reload()
        
        if failed_employees:
            error_msg = _("Failed to create salary history for:\n") + "\n".join(failed_employees)
            frappe.throw(error_msg)
        
        frappe.msgprint(
            _("Successfully created and submitted {0} Salary History record(s)").format(len(created_records)), 
            indicator="green"
        )
        return created_records
    
    def on_submit(self):
        """Create Salary History records when document is submitted"""
        if not self.employees:
            frappe.throw(_("Cannot submit without employees"))
        
        self.create_salary_history_records()
    
    def on_cancel(self):
        """Cancel all related Salary History records"""
        # Find all Salary History records created by this bulk increment
        # They have remarks containing this document's name
        salary_histories = frappe.get_all(
            "Salary History",
            filters={
                "remarks": ["like", f"%{self.name}%"],
                "docstatus": 1
            },
            fields=["name", "employee"]
        )
        
        if not salary_histories:
            return
        
        cancelled_count = 0
        failed_cancellations = []
        
        for sh in salary_histories:
            try:
                sh_doc = frappe.get_doc("Salary History", sh.name)
                if sh_doc.docstatus == 1:
                    sh_doc.cancel()
                    cancelled_count += 1
            except Exception as e:
                emp_name = sh.employee
                failed_cancellations.append(f"{emp_name}: {str(e)}")
                frappe.log_error(
                    title=f"Error cancelling salary history {sh.name}",
                    message=f"Employee: {emp_name}\nError: {str(e)}\nTraceback: {frappe.get_traceback()}"
                )
                continue
        
        if failed_cancellations:
            error_msg = _("Failed to cancel salary history records:\n") + "\n".join(failed_cancellations)
            frappe.throw(error_msg)
        
        if cancelled_count:
            frappe.msgprint(_("Cancelled {0} related Salary History records").format(cancelled_count), indicator="orange")
    
    def before_save(self):
        """Actions before saving"""
        # Ensure status is always Active
        if not self.status:
            self.status = "Active"
        self.number_of_employees = len(self.employees) if self.employees else 0
