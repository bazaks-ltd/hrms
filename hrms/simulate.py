import frappe
from faker import Faker

@frappe.whitelist()
def create_employees(number_of_employees, name, department, designation):
    fake = Faker()

    for idx in range(number_of_employees):
        print(idx)
        # first_name = fake.first_name()
        first_name = name + " " + str(idx+1)
        # last_name = fake.last_name()
        employee_name = f"{first_name}"
        email = fake.email()
        gender = fake.random_element(elements=('Male', 'Female'))
        date_of_birth = fake.date_of_birth(minimum_age=20, maximum_age=60)

        employee = frappe.get_doc({
            "doctype": "Employee",
            "employee_name": employee_name,
            "first_name": first_name,
            # "last_name": last_name,
            "company": "Premium Care Clinic",
            "department": department,
            "designation": designation,
            "gender": gender,
            "date_of_birth": date_of_birth,
            "email": email,
            "status": "Active",
            "date_of_joining": fake.date_this_decade()
        })

        employee.insert()
        frappe.db.commit()

        print(f"Created employee: {employee_name}")
