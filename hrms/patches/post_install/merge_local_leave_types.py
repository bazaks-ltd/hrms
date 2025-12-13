# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute():
	"""
	Merge Local Leave Er and Local Leave Ee into Local Leave
	
	This patch:
	1. Updates all Leave Allocations from old types to "Local Leave"
	2. Updates all Leave Applications referencing old types
	3. Updates Leave Ledger Entries
	4. Updates Leave Policy Details
	5. Deletes old leave types after migration
	"""
	
	old_leave_types = ["Local Leave Er", "Local Leave Ee"]
	new_leave_type = "Local Leave"
	
	# Create new leave type if it doesn't exist
	if not frappe.db.exists("Leave Type", new_leave_type):
		print(f"\nCreating Leave Type: {new_leave_type}...")
		# Get configuration from one of the old types (prefer Local Leave Er)
		source_type = None
		for old_type in old_leave_types:
			if frappe.db.exists("Leave Type", old_type):
				source_type = frappe.get_doc("Leave Type", old_type)
				break
		
		if source_type:
			# Create new leave type based on source type, matching fixture configuration
			new_leave_type_doc = frappe.new_doc("Leave Type")
			new_leave_type_doc.leave_type_name = new_leave_type
			new_leave_type_doc.max_leaves_allowed = 11.0  # Match fixture
			new_leave_type_doc.include_holiday = 0
			new_leave_type_doc.is_lwp = 0
			new_leave_type_doc.is_compensatory = 0
			new_leave_type_doc.is_earned_leave = 0
			new_leave_type_doc.allow_encashment = 1
			new_leave_type_doc.earning_component = "Leave Encashment"
			new_leave_type_doc.applicable_after = 365  # 1 year from joining
			new_leave_type_doc.allocate_on_day = "Last Day"
			new_leave_type_doc.earned_leave_frequency = "Monthly"
			new_leave_type_doc.insert(ignore_permissions=True)
			print(f"  ✓ Created Leave Type: {new_leave_type}")
		else:
			# If no source type exists, create with default values matching fixture
			new_leave_type_doc = frappe.new_doc("Leave Type")
			new_leave_type_doc.leave_type_name = new_leave_type
			new_leave_type_doc.max_leaves_allowed = 11.0
			new_leave_type_doc.include_holiday = 0
			new_leave_type_doc.is_lwp = 0
			new_leave_type_doc.is_compensatory = 0
			new_leave_type_doc.is_earned_leave = 0
			new_leave_type_doc.allow_encashment = 1
			new_leave_type_doc.earning_component = "Leave Encashment"
			new_leave_type_doc.applicable_after = 365
			new_leave_type_doc.allocate_on_day = "Last Day"
			new_leave_type_doc.earned_leave_frequency = "Monthly"
			new_leave_type_doc.insert(ignore_permissions=True)
			print(f"  ✓ Created Leave Type: {new_leave_type} with default values")
	
	print("=" * 80)
	print("Merging Local Leave Types")
	print("=" * 80)
	
	# 1. Update Leave Applications FIRST (before allocations to avoid validation errors)
	print("\n1. Updating Leave Applications...")
	applications_updated = 0
	
	for old_type in old_leave_types:
		if frappe.db.exists("Leave Type", old_type):
			applications = frappe.get_all(
				"Leave Application",
				filters={"leave_type": old_type, "docstatus": ("!=", 2)},
				fields=["name"]
			)
			
			for app in applications:
				frappe.db.set_value("Leave Application", app.name, "leave_type", new_leave_type, update_modified=False)
				applications_updated += 1
				print(f"  - Updated application {app.name}")
	
	print(f"  ✓ Updated {applications_updated} Leave Applications")
	
	# 2. Update Leave Allocations (after applications are updated)
	print("\n2. Updating Leave Allocations...")
	allocations_updated = 0
	
	for old_type in old_leave_types:
		if frappe.db.exists("Leave Type", old_type):
			allocations = frappe.get_all(
				"Leave Allocation",
				filters={"leave_type": old_type, "docstatus": ("!=", 2)},
				fields=["name", "employee", "from_date", "to_date", "new_leaves_allocated", "total_leaves_allocated"]
			)
			
			for allocation in allocations:
				# Check if there's already an allocation for Local Leave in the same period
				existing = frappe.db.exists(
					"Leave Allocation",
					{
						"employee": allocation.employee,
						"leave_type": new_leave_type,
						"from_date": allocation.from_date,
						"to_date": allocation.to_date,
						"docstatus": ("!=", 2)
					}
				)
				
				if existing:
					# Merge allocations - add leaves together using direct SQL to avoid validation
					old_alloc_data = frappe.db.get_value(
						"Leave Allocation",
						allocation.name,
						["new_leaves_allocated", "total_leaves_allocated"],
						as_dict=True
					)
					
					new_alloc_data = frappe.db.get_value(
						"Leave Allocation",
						existing,
						["new_leaves_allocated", "total_leaves_allocated"],
						as_dict=True
					)
					
					# Update using direct SQL to bypass validation
					frappe.db.sql("""
						UPDATE `tabLeave Allocation`
						SET new_leaves_allocated = %s,
							total_leaves_allocated = %s
						WHERE name = %s
					""", (
						flt(new_alloc_data.new_leaves_allocated) + flt(old_alloc_data.new_leaves_allocated),
						flt(new_alloc_data.total_leaves_allocated) + flt(old_alloc_data.total_leaves_allocated),
						existing
					))
					
					# Update Leave Ledger Entries to point to the merged allocation
					# This is critical - orphaned ledger entries won't be included in balance calculations
					ledger_updated = frappe.db.sql("""
						UPDATE `tabLeave Ledger Entry`
						SET transaction_name = %s
						WHERE transaction_name = %s
						AND transaction_type = 'Leave Allocation'
					""", (existing, allocation.name))
					
					# Delete old allocation using direct SQL (bypassing cancel requirement)
					frappe.db.sql("""
						DELETE FROM `tabLeave Allocation` WHERE name = %s
					""", (allocation.name,))
					
					print(f"  - Merged allocation {allocation.name} into {existing} (updated {ledger_updated} ledger entries)")
				else:
					# Simply update the leave type using direct SQL to bypass validation
					frappe.db.sql("""
						UPDATE `tabLeave Allocation`
						SET leave_type = %s
						WHERE name = %s
					""", (new_leave_type, allocation.name))
					print(f"  - Updated allocation {allocation.name}")
				
				allocations_updated += 1
	
	print(f"  ✓ Updated {allocations_updated} Leave Allocations")
	
	# 3. Update Leave Ledger Entries
	print("\n3. Updating Leave Ledger Entries...")
	ledger_updated = 0
	
	for old_type in old_leave_types:
		if frappe.db.exists("Leave Type", old_type):
			# Use direct SQL to update ledger entries
			frappe.db.sql("""
				UPDATE `tabLeave Ledger Entry`
				SET leave_type = %s
				WHERE leave_type = %s
			""", (new_leave_type, old_type))
			
			count = frappe.db.sql("""
				SELECT COUNT(*) as count
				FROM `tabLeave Ledger Entry`
				WHERE leave_type = %s
			""", (old_type,), as_dict=True)
			
			ledger_updated += count[0].count if count else 0
	
	print(f"  ✓ Updated {ledger_updated} Leave Ledger Entries")
	
	# 4. Update Leave Policy Details
	print("\n4. Updating Leave Policy Details...")
	policy_details_updated = 0
	
	for old_type in old_leave_types:
		if frappe.db.exists("Leave Type", old_type):
			policy_details = frappe.get_all(
				"Leave Policy Detail",
				filters={"leave_type": old_type},
				fields=["name", "parent", "annual_allocation"]
			)
			
			for detail in policy_details:
				# Check if Local Leave already exists in this policy
				existing_detail = frappe.db.exists(
					"Leave Policy Detail",
					{
						"parent": detail.parent,
						"leave_type": new_leave_type
					}
				)
				
				if existing_detail:
					# Merge annual allocations using direct SQL
					existing_alloc = frappe.db.get_value(
						"Leave Policy Detail",
						existing_detail,
						"annual_allocation"
					)
					
					frappe.db.sql("""
						UPDATE `tabLeave Policy Detail`
						SET annual_allocation = %s
						WHERE name = %s
					""", (
						flt(existing_alloc) + flt(detail.annual_allocation),
						existing_detail
					))
					
					# Delete old policy detail
					frappe.db.sql("""
						DELETE FROM `tabLeave Policy Detail` WHERE name = %s
					""", (detail.name,))
					
					print(f"  - Merged policy detail {detail.name} into {existing_detail}")
				else:
					# Update leave type
					frappe.db.sql("""
						UPDATE `tabLeave Policy Detail`
						SET leave_type = %s
						WHERE name = %s
					""", (new_leave_type, detail.name))
					print(f"  - Updated policy detail {detail.name}")
				
				policy_details_updated += 1
	
	print(f"  ✓ Updated {policy_details_updated} Leave Policy Details")
	
	# 5. Update Leave Encashment (if any)
	print("\n5. Updating Leave Encashment...")
	encashment_updated = 0
	
	for old_type in old_leave_types:
		if frappe.db.exists("Leave Type", old_type):
			# Use direct SQL to update encashments
			frappe.db.sql("""
				UPDATE `tabLeave Encashment`
				SET leave_type = %s
				WHERE leave_type = %s AND docstatus != 2
			""", (new_leave_type, old_type))
			
			count = frappe.db.sql("""
				SELECT COUNT(*) as count
				FROM `tabLeave Encashment`
				WHERE leave_type = %s AND docstatus != 2
			""", (old_type,), as_dict=True)
			
			encashment_updated += count[0].count if count else 0
	
	print(f"  ✓ Updated {encashment_updated} Leave Encashment records")
	
	# 6. Delete old leave types
	print("\n6. Deleting old Leave Types...")
	for old_type in old_leave_types:
		if frappe.db.exists("Leave Type", old_type):
			# Check if there are any remaining references
			remaining_refs = frappe.db.sql("""
				SELECT COUNT(*) as count FROM (
					SELECT 'Leave Allocation' as doctype, name FROM `tabLeave Allocation` WHERE leave_type = %s
					UNION ALL
					SELECT 'Leave Application', name FROM `tabLeave Application` WHERE leave_type = %s
					UNION ALL
					SELECT 'Leave Ledger Entry', name FROM `tabLeave Ledger Entry` WHERE leave_type = %s
					UNION ALL
					SELECT 'Leave Policy Detail', name FROM `tabLeave Policy Detail` WHERE leave_type = %s
				) as refs
			""", (old_type, old_type, old_type, old_type), as_dict=1)
			
			if remaining_refs[0].count == 0:
				frappe.delete_doc("Leave Type", old_type, force=1)
				print(f"  ✓ Deleted Leave Type: {old_type}")
			else:
				print(f"  ⚠ Warning: Cannot delete {old_type} - {remaining_refs[0].count} references still exist")
	
	# Clear cache
	frappe.clear_cache(doctype="Leave Type")
	frappe.clear_cache(doctype="Leave Allocation")
	frappe.clear_cache(doctype="Leave Application")
	
	frappe.db.commit()
	
	print("\n" + "=" * 80)
	print("Merge completed successfully!")
	print("=" * 80 + "\n")


