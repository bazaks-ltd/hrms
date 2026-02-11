# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""
Utility script to verify and configure all 22 MO leave types.
Run this script to ensure all leave types exist and are configured correctly.
"""

import frappe
from frappe import _


REQUIRED_LEAVE_TYPES = [
	"Bank Sick Leave",
	"Bank Local Leave",
	"Unpaid Sick Leave",
	"Local Leave",
	"Paternity Leave",
	"Maternity Leave",
	"Vacation Leave",
	"Sick Leave",
	"Compassionate Leave",
	"Wedding Leave",
	"Special Leave",
	"Monthly Local Leave",
	"Monthly Sick Leave",
	"Compensatory Off",
	"Leave Without Pay",
	"Training Leave (Paid)",
	"Unpaid Local Leave",
	"Unauthorized Leave",
	"Injury Leave",
	"Injury Unpaid Leave",
	"Privilege Leave",
	"Casual Leave",
]

UNPAID_LEAVE_TYPES = [
	"Unpaid Sick Leave",
	"Unpaid Local Leave",
	"Leave Without Pay",
	"Injury Unpaid Leave",
]


def verify_and_configure_leave_types():
	"""Verify all leave types exist and configure them correctly"""
	missing_types = []
	configured_types = []

	for leave_type_name in REQUIRED_LEAVE_TYPES:
		if not frappe.db.exists("Leave Type", leave_type_name):
			missing_types.append(leave_type_name)
			_create_leave_type(leave_type_name)
		else:
			_configure_leave_type(leave_type_name)
			configured_types.append(leave_type_name)

	result = {
		"missing": missing_types,
		"configured": configured_types,
		"total": len(REQUIRED_LEAVE_TYPES),
	}

	frappe.msgprint(
		_("Leave Types Verification Complete:\n- Total: {0}\n- Configured: {1}\n- Created: {2}").format(
			result["total"], len(configured_types), len(missing_types)
		),
		indicator="green",
		title=_("Verification Complete"),
	)

	return result


def _create_leave_type(leave_type_name):
	"""Create a new leave type with default configuration"""
	leave_type = frappe.get_doc(
		{
			"doctype": "Leave Type",
			"leave_type_name": leave_type_name,
			"max_leaves_allowed": 0,
			"is_carry_forward": 0,
			"is_lwp": 1 if leave_type_name in UNPAID_LEAVE_TYPES or "Without Pay" in leave_type_name else 0,
			"allow_negative": 0,
			"allow_over_allocation": 0,
			"include_holiday": 0,
			"is_compensatory": 0,
			"is_earned_leave": 0,
			"is_optional_leave": 0,
			"allow_encashment": 0,
		}
	)
	leave_type.insert(ignore_permissions=True)
	frappe.db.commit()
	return leave_type.name


def _configure_leave_type(leave_type_name):
	"""Configure existing leave type to ensure all fields are set correctly"""
	leave_type = frappe.get_doc("Leave Type", leave_type_name)
	updated = False

	# Set all numeric fields to 0
	if leave_type.max_leaves_allowed != 0:
		leave_type.max_leaves_allowed = 0
		updated = True

	# Set all checkbox fields to unchecked
	checkbox_fields = [
		"is_carry_forward",
		"allow_negative",
		"allow_over_allocation",
		"include_holiday",
		"is_compensatory",
		"is_earned_leave",
		"is_optional_leave",
		"allow_encashment",
	]

	for field in checkbox_fields:
		if getattr(leave_type, field, 0) != 0:
			setattr(leave_type, field, 0)
			updated = True

	# Set is_lwp for unpaid leaves
	is_unpaid = leave_type_name in UNPAID_LEAVE_TYPES or "Without Pay" in leave_type_name
	if is_unpaid and not leave_type.is_lwp:
		leave_type.is_lwp = 1
		updated = True
	elif not is_unpaid and leave_type.is_lwp:
		leave_type.is_lwp = 0
		updated = True

	if updated:
		leave_type.save(ignore_permissions=True)
		frappe.db.commit()


@frappe.whitelist()
def run_verification():
	"""Whitelisted method to run verification"""
	return verify_and_configure_leave_types()
