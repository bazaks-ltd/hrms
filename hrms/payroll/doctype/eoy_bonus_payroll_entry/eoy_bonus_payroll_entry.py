# eoy_bonus_payroll_entry.py

import frappe
from frappe import _
from frappe.utils import getdate, flt, cint, date_diff, add_months, get_first_day, get_last_day
from frappe.model.document import Document
from datetime import date
from hrms.payroll.doctype.payroll_entry.payroll_entry import PayrollEntry, get_end_date, get_employee_list

class EOYBonusPayrollEntry(Document):
    
    def autoname(self):
        start_year = getdate(self.bonus_period_start).year
        end_year = getdate(self.bonus_period_end).year
        if start_year == end_year:
            self.name = f"HR-EOY-{start_year}-{frappe.generate_hash(length=5)}"
        else:
            self.name = f"HR-EOY-{start_year}-{end_year}-{frappe.generate_hash(length=5)}"
    
    def validate(self):
        self.validate_bonus_period()
        self.validate_payroll_dates()
        self.validate_employees()
        self.calculate_bonus_amounts()
        self.calculate_totals()
        
    def validate_bonus_period(self):
        """Validate bonus period dates"""
        if getdate(self.bonus_period_start) >= getdate(self.bonus_period_end):
            frappe.throw(_("Bonus Period Start Date must be before End Date"))
        
        # Optional: Validate that it's typically a year period
        period_days = date_diff(self.bonus_period_end, self.bonus_period_start)
        if period_days > 400:  # More than ~13 months
            frappe.msgprint(_("Bonus period is longer than typical annual period"), indicator="yellow")
    
    def validate_payroll_dates(self):
        """Validate salary slip dates"""
        if not self.start_date or not self.end_date:
            frappe.throw(_("Please set both Salary Slip Start Date and End Date"))
            
        if getdate(self.start_date) >= getdate(self.end_date):
            frappe.throw(_("Salary Slip Start Date must be before End Date"))
        
        # Optional: Warning if salary slip dates are before bonus period end
        if getdate(self.end_date) < getdate(self.bonus_period_end):
            frappe.msgprint(
                _("Salary slip dates are before bonus period end. This is unusual but allowed."), 
                indicator="yellow"
            )
    
    def make_filters(self):
        filters = frappe._dict(
            company=self.company,
            branch=self.branch,
            department=self.department,
            designation=self.designation,
            grade=self.grade,
            currency=self.currency,
            start_date=self.start_date,
            end_date=self.end_date,
            payroll_payable_account=self.payroll_payable_account,
            salary_slip_based_on_timesheet=self.salary_slip_based_on_timesheet,
        )

        if not self.salary_slip_based_on_timesheet:
            filters.update(dict(payroll_frequency=self.payroll_frequency))

        return filters
    
    @frappe.whitelist()
    def get_employees_with_unmarked_attendance(self) -> list[dict] | None:
        if not self.validate_attendance:
            return

        unmarked_attendance = []
        employee_details = self.get_employee_and_attendance_details()
        default_holiday_list = frappe.db.get_value(
            "Company", self.company, "default_holiday_list", cache=True
        )

        for emp in self.employees:
            details = next((record for record in employee_details if record.name == emp.employee), None)
            if not details:
                continue

            start_date, end_date = self.get_payroll_dates_for_employee(details)
            holidays = self.get_holidays_count(
                details.holiday_list or default_holiday_list, start_date, end_date
            )
            payroll_days = date_diff(end_date, start_date) + 1
            unmarked_days = payroll_days - (holidays + details.attendance_count)

            if unmarked_days > 0:
                unmarked_attendance.append(
                    {
                        "employee": emp.employee,
                        "employee_name": emp.employee_name,
                        "unmarked_days": unmarked_days,
                    }
                )

        return unmarked_attendance

    def get_employee_and_attendance_details(self) -> list[dict]:
        """Returns a list of employee and attendance details like
        [
                {
                        "name": "HREMP00001",
                        "date_of_joining": "2019-01-01",
                        "relieving_date": "2022-01-01",
                        "holiday_list": "Holiday List Company",
                        "attendance_count": 22
                }
        ]
        """
        employees = [emp.employee for emp in self.employees]

        Employee = frappe.qb.DocType("Employee")
        Attendance = frappe.qb.DocType("Attendance")

        return (
            frappe.qb.from_(Employee)
            .left_join(Attendance)
            .on(
                (Employee.name == Attendance.employee)
                & (Attendance.attendance_date.between(self.start_date, self.end_date))
                & (Attendance.docstatus == 1)
            )
            .select(
                Employee.name,
                Employee.date_of_joining,
                Employee.relieving_date,
                Employee.holiday_list,
                Count(Attendance.name).as_("attendance_count"),
            )
            .where(Employee.name.isin(employees))
            .groupby(Employee.name)
        ).run(as_dict=True)
    
    def validate_employees(self):
        """Validate employee eligibility"""
        if not self.employees:
            return
            
        for emp in self.employees:
            # Check if employee was employed during the bonus period
            employee_doc = frappe.get_doc("Employee", emp.employee)
            
            if employee_doc.date_of_joining > getdate(self.bonus_period_end):
                frappe.throw(_("Employee {0} joined after bonus period").format(emp.employee_name))
    
    @frappe.whitelist()
    def get_employees(self):
        """Fetch employees based on filters"""
        filters = {
            "status": "Active",
            "company": self.company
        }
        
        # Add optional filters
        if self.department:
            filters["department"] = self.department
        if self.branch:
            filters["branch"] = self.branch
        if self.designation:
            filters["designation"] = self.designation
        if self.grade:
            filters["grade"] = self.grade
        if self.employment_type:
            filters["employment_type"] = self.employment_type
        if self.include_employees_joined_after:
            filters["date_of_joining"] = [">=", self.include_employees_joined_after]
        
        employees = frappe.get_all("Employee", 
            filters=filters,
            fields=["name", "employee_name", "nid", "date_of_joining", "relieving_date", "department"]
        )
        
        # Clear existing employees
        self.set("employees", [])
        
        # Add filtered employees with calculations
        for emp in employees:
            self.append("employees", {
                "employee": emp.name,
                "employee_name": emp.employee_name,
                "nid": emp.nid,
                "joining_date": emp.date_of_joining,
                "department": emp.department
            })
        
        self.calculate_bonus_amounts()
        self.number_of_employees = len(self.employees)
    
    @frappe.whitelist()
    def fill_employee_details(self):
        filters = self.make_filters()
        employees = get_employee_list(filters=filters, as_dict=True, ignore_match_conditions=True)
        self.set("employees", [])

        if not employees:
            error_msg = _(
                "No employees found for the mentioned criteria:<br>Company: {0}<br> Currency: {1}<br>Payroll Payable Account: {2}"
            ).format(
                frappe.bold(self.company),
                frappe.bold(self.currency),
                frappe.bold(self.payroll_payable_account),
            )
            if self.branch:
                error_msg += "<br>" + _("Branch: {0}").format(frappe.bold(self.branch))
            if self.department:
                error_msg += "<br>" + _("Department: {0}").format(frappe.bold(self.department))
            if self.designation:
                error_msg += "<br>" + _("Designation: {0}").format(frappe.bold(self.designation))
            if self.start_date:
                error_msg += "<br>" + _("Start date: {0}").format(frappe.bold(self.start_date))
            if self.end_date:
                error_msg += "<br>" + _("End date: {0}").format(frappe.bold(self.end_date))
            frappe.throw(error_msg, title=_("No employees found"))

        self.set("employees", employees)
        self.number_of_employees = len(self.employees)

        return self.get_employees_with_unmarked_attendance()


    def calculate_bonus_amounts(self):
        """Calculate bonus amounts for all employees"""
        if not self.employees:
            return
            
        for emp in self.employees:
            # Calculate service period within bonus period
            joining_date = getdate(emp.joining_date) if emp.joining_date else getdate(self.bonus_period_start)
            # leaving_date = getdate(emp.relieving_date) if emp.relieving_date else None
            
            # Determine effective service period within bonus period
            service_start = max(joining_date, getdate(self.bonus_period_start))
            # TODO: consider relieving date
            service_end = getdate(self.bonus_period_end)
            
            # Check if employee worked during bonus period
            if service_start > service_end:
                emp.eligible = 0
                emp.eligibility_reason = "Did not work during bonus period"
                continue
            
            # Calculate service days/months
            service_days = date_diff(service_end, service_start) + 1
            service_months = service_days / 30.44  # Average days per month
            
            # Check eligibility
            min_service = 6
            eligible = service_months >= min_service
            
            if not eligible:
                emp.eligible = 0
                emp.eligibility_reason = f"Service period {service_months:.1f} months < required {min_service} months"
                continue
                
            # Calculate remuneration for the bonus period
            # total_remuneration = self.get_employee_period_remuneration(
            #     emp.employee, 
            #     self.bonus_period_start, 
            #     self.bonus_period_end
            # )

            total_remuneration = 24000000
            
            # Calculate proration factor if enabled
            prorate_factor = 1.0
           
            # Calculate bonus amount
            bonus_percentage = 8.33
            calculated_bonus = flt(total_remuneration * bonus_percentage / 100 * prorate_factor)
            
            # Update employee record
            emp.service_months = round(service_months, 1)
            emp.service_days = service_days
            emp.eligible = 1 if eligible else 0
            emp.eligibility_reason = "Eligible" if eligible else f"Service {service_months:.1f} months < required {min_service}"
            emp.total_remuneration = total_remuneration
            emp.prorate_factor = prorate_factor * 100  # Store as percentage
            
            emp.final_bonus = calculated_bonus
    
    def get_basic_salary_for_period(self, employee, start_date, end_date):
        """Calculate basic salary total for the period"""
        salary_slips = frappe.get_all(
            "Salary Slip",
            filters={
                "employee": employee,
                "start_date": [">=", start_date],
                "end_date": ["<=", end_date],
                "docstatus": 1
            },
            fields=["name"]
        )
        
        total_basic = 0
        for slip in salary_slips:
            basic_amount = frappe.db.get_value(
                "Salary Detail",
                {
                    "parent": slip.name,
                    "salary_component": "Basic",
                    "parentfield": "earnings"
                },
                "amount"
            )
            if basic_amount:
                total_basic += basic_amount
        
        return total_basic
    
    def calculate_totals(self):
        """Calculate total amounts"""
        if not self.employees:
            self.total_bonus_amount = 0
            self.payable_amount = 0
            return
        
        total_bonus = sum(flt(emp.final_bonus) for emp in self.employees if emp.eligible)
        self.total_bonus_amount = total_bonus
        self.payable_amount = total_bonus  # May include other calculations later
    
    @frappe.whitelist()
    def validate_bonus_amounts(self):
        """Validate all bonus calculations"""
        self.calculate_bonus_amounts()
        self.calculate_totals()
        frappe.msgprint(_("Bonus amounts validated and updated"))
    
    @frappe.whitelist()
    def create_salary_slips(self):
        print("Creating salary slips for EOY bonus payroll entry", self.name)
        """Create 13th month salary slips for all employees"""
        if self.salary_slips_created:
            frappe.throw(_("Salary slips already created for this bonus entry"))
        
        # Ensure the payroll entry has the configured Salary Structure Assignment
        ss = frappe.get_doc("Salary Structure", "EOY SS 2025 v3")

        created_slips = []
        failed_employees = []
        
        for emp in self.employees:
            print("Employee: ", emp.employee_name)
            if not emp.eligible or flt(emp.final_bonus) <= 0:
                continue
                
            try:
                last_slips = frappe.get_all(
                    "Salary Slip",
                    filters={
                        "employee": emp.employee,
                        "start_date": [">=", self.bonus_period_start],
                        "end_date": ["<=", self.bonus_period_end],
                        "docstatus": 1,
                    },
                    fields=["name", "start_date", "end_date"],
                    order_by="end_date desc",
                    limit_page_length=1,
                )
                last_salary_slip = frappe.get_doc("Salary Slip", last_slips[0].name) if last_slips else None
                print("Last Salary Slip: ", last_salary_slip)
                print("Bonus Period Start: ", self.bonus_period_start)
                print("Bonus Period End: ", self.bonus_period_end)
                emoluments_data = None
                if last_salary_slip:
                    try:
                        emoluments_data = last_salary_slip.compute_period_emoluments_eoy(
                            period_start_date=self.bonus_period_start,
                            period_end_date=self.bonus_period_end
                        )
                    except Exception:
                        emoluments_data = None

                print("Emoluments Data: ", emoluments_data)
                            
                if emoluments_data: 
                    basic_total = 0
                    for s in emoluments_data.get("salary_slips", []):
                            slip_name = s.get("name")
                            if not slip_name:
                                continue
                            amt = frappe.db.get_value(
                                "Salary Detail",
                                {"parent": slip_name, "parentfield": "earnings", "salary_component": "Basic"},
                                "amount",
                            ) or 0
                            basic_total += flt(amt)
                    bonus_base = (1/12) * basic_total
                else:
                    bonus_base = 0

                print("Bonus Base: ", bonus_base)

                # Create salary slip
                salary_slip = frappe.new_doc("Salary Slip")
                salary_slip.employee = emp.employee
                salary_slip.employee_name = emp.employee_name
                salary_slip.company = self.company
                salary_slip.posting_date = self.posting_date
                salary_slip.start_date = self.start_date
                salary_slip.end_date = self.end_date
                
                salary_slip.salary_structure = ss.name

                salary_slip.is_thirteenth_month = 1
                
                # Link to this payroll entry
                # salary_slip.payroll_entry = self.name
                # salary_slip.letter_head = self.letter_head
                
                # Set basic payroll fields
                salary_slip.payroll_frequency = "Monthly"
                salary_slip.total_working_days = 1
                salary_slip.payment_days = 1
                salary_slip.leave_without_pay = 0
                salary_slip.absent_days = 0
                
                # Add EOY bonus as earning
                salary_slip.append("earnings", {
                    "salary_component": "EOY",
                    "abbr": "eoy",
                    "amount": bonus_base,
                    "default_amount": emp.final_bonus,
                    "additional_amount": 0,
                    "is_tax_applicable": 1,
                    "do_not_include_in_total": 0
                })
                
                # Set currency and exchange rate
                salary_slip.currency = self.currency
                salary_slip.exchange_rate = self.exchange_rate
                
                # Calculate net pay
                salary_slip.calculate_net_pay()
                salary_slip.save()
                
                # Update employee record with salary slip reference
                emp.salary_slip = salary_slip.name
                created_slips.append(salary_slip.name)
                
            except Exception as e:
                failed_employees.append(f"{emp.employee_name}: {str(e)}")
                continue
        
        if failed_employees:
            error_msg = _("Failed to create salary slips for:\n") + "\n".join(failed_employees)
            frappe.throw(error_msg)
        
        # self.salary_slips_created = 1
        # self.status = "Submitted"
        self.save()
        
        frappe.msgprint(_("Created {0} 13th month salary slips").format(len(created_slips)))
        return created_slips
    
    @frappe.whitelist()
    def submit_salary_slips(self):
        """Submit all created salary slips"""
        if not self.salary_slips_created:
            frappe.throw(_("Please create salary slips first"))
        
        salary_slips = [emp.salary_slip for emp in self.employees if emp.salary_slip]
        submitted_count = 0
        failed_submissions = []
        
        for slip_name in salary_slips:
            try:
                slip = frappe.get_doc("Salary Slip", slip_name)
                if slip.docstatus == 0:
                    slip.submit()
                    submitted_count += 1
            except Exception as e:
                failed_submissions.append(f"{slip_name}: {str(e)}")
                continue
        
        if failed_submissions:
            error_msg = _("Failed to submit salary slips:\n") + "\n".join(failed_submissions)
            frappe.throw(error_msg)
        
        self.salary_slips_submitted = 1
        self.save()
        
        frappe.msgprint(_("Submitted {0} salary slips").format(submitted_count))
    
    def on_submit(self):
        """Actions on document submission"""
        if not self.employees:
            frappe.throw(_("Cannot submit without employees"))
        
        # Validate all calculations
        self.calculate_bonus_amounts()
        self.calculate_totals()
        self.create_salary_slips()
    
    def on_cancel(self):
        """Cancel related salary slips"""
        if self.salary_slips_created:
            # Cancel and delete related salary slips
            for emp in self.employees:
                if emp.salary_slip:
                    try:
                        slip_doc = frappe.get_doc("Salary Slip", emp.salary_slip)
                        if slip_doc.docstatus == 1:
                            slip_doc.cancel()
                        slip_doc.delete()
                        emp.salary_slip = ""
                    except Exception as e:
                        frappe.log_error(f"Error cancelling salary slip {emp.salary_slip}: {str(e)}")
                        continue
        
        self.salary_slips_created = 0
        self.salary_slips_submitted = 0
        self.status = "Cancelled"
    
    def before_save(self):
        """Actions before saving"""
        self.number_of_employees = len(self.employees) if self.employees else 0