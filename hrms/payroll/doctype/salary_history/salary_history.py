import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt

class SalaryHistory(Document):

    def before_insert(self):
        self.fetch_previous_salary()

    def validate(self):
        # Fetch previous salary if not already set or if employee changed
        if not self.previous_basic_salary or self.has_value_changed('employee'):
            self.fetch_previous_salary()
        self.validate_employee()
        self.calculate_new_salary()
        self.calculate_percentage()
        self.validate_effective_date()
        self.validate_salary_amount()

    def fetch_previous_salary(self):
        """Fetch current basic salary from Employee record"""
        if self.employee:
            current_salary = frappe.db.get_value('Employee', self.employee, 'e_basic')
            self.previous_basic_salary = flt(current_salary) or 0

    def validate_employee(self):
        """Ensure employee is active"""
        employee_status = frappe.db.get_value('Employee', self.employee, 'status')
        if employee_status != 'Active':
            frappe.throw(f'Cannot create salary history for inactive employee')

    def calculate_new_salary(self):
        """Calculate new salary from change amount"""
        prev_salary = flt(self.previous_basic_salary)
        change = flt(self.change_amount)
        self.new_basic_salary = prev_salary + change

    def calculate_percentage(self):
        """Calculate change percentage"""
        prev_salary = flt(self.previous_basic_salary)
        change = flt(self.change_amount)
        if prev_salary:
            self.change_percentage = change / prev_salary * 100
        else:
            self.change_percentage = 0

    def validate_effective_date(self):
        """Ensure no duplicate history records on same date"""
        existing = frappe.db.exists('Salary History', {'employee': self.employee, 'effective_from_date': self.effective_from_date, 'name': ['!=', self.name], 'docstatus': ['!=', 2]})
        if existing:
            frappe.throw(f'A salary history record already exists for {self.employee} on {self.effective_from_date}')

    def validate_salary_amount(self):
        """Basic validation for salary amount"""
        if flt(self.new_basic_salary) <= 0:
            frappe.throw('New Basic Salary must be greater than zero')
        if self.change_amount < 0:
            if abs(self.change_percentage) > 20:
                frappe.msgprint(f'Warning: This is a salary decrease of {abs(self.change_percentage):.2f}%', indicator='orange', alert=True)

    def on_submit(self):
        """Update Employee's e_basic field when submitted"""
        self.update_employee_salary()
        self.add_comment_to_employee()

    def on_cancel(self):
        """Revert Employee's e_basic when cancelled"""
        self.revert_employee_salary()
        self.add_comment_to_employee(cancelled=True)

    def update_employee_salary(self):
        """Update the Employee master with new salary"""
        frappe.db.set_value('Employee', self.employee, 'e_basic', self.new_basic_salary, update_modified=True)
        change_direction = 'increased' if self.change_amount > 0 else 'decreased' if self.change_amount < 0 else 'updated'
        frappe.msgprint(f"Employee {self.employee} basic salary {change_direction} to {frappe.format_value(self.new_basic_salary, 'Currency')}", indicator='green', alert=True)

    def revert_employee_salary(self):
        """Revert to previous salary when cancelled"""
        previous_record = frappe.get_all('Salary History', filters={'employee': self.employee, 'docstatus': 1, 'effective_from_date': ['<', self.effective_from_date], 'name': ['!=', self.name]}, fields=['new_basic_salary'], order_by='effective_from_date desc', limit=1)
        if previous_record:
            revert_to = previous_record[0].new_basic_salary
        else:
            revert_to = self.previous_basic_salary
        frappe.db.set_value('Employee', self.employee, 'e_basic', revert_to, update_modified=True)
        frappe.msgprint(f"Employee {self.employee} basic salary reverted to {frappe.format_value(revert_to, 'Currency')}", indicator='orange', alert=True)

    def add_comment_to_employee(self, cancelled=False):
        """Add a comment to Employee for audit trail"""
        employee_doc = frappe.get_doc('Employee', self.employee)
        if cancelled:
            comment = f'Salary history record {self.name} was cancelled. Salary reverted.'
        else:
            comment = f"Salary changed from {frappe.format_value(self.previous_basic_salary, 'Currency')} to {frappe.format_value(self.new_basic_salary, 'Currency')} ({self.change_percentage:+.2f}%). Reason: {self.change_type}"
        employee_doc.add_comment('Info', comment)

@frappe.whitelist()
def get_employee_basic_salary(employee):
    """Get employee's current basic salary (e_basic) from Employee record"""
    if not employee:
        return 0
    
    e_basic = frappe.db.get_value('Employee', employee, 'e_basic')
    return flt(e_basic) or 0