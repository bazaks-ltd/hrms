import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.desk.page.setup_wizard.install_fixtures import (
	_,  # NOTE: this is not the real translation function
)

def execute():
    custom_fields = {
        "Department": [
            {
				"fieldname": "overtime_approvers",
				"fieldtype": "Table",
				"label": _("Overtime Approver"),
				"options": "Department Approver",
				"insert_after": "shift_request_approver",
			},
        ]
    }

    create_custom_fields(custom_fields)