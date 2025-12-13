# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe


def execute():
	"""
	Fix orphaned Leave Ledger Entries for Local Leave
	
	After merging Local Leave Er and Local Leave Ee into Local Leave,
	some Leave Ledger Entries may point to deleted allocations.
	This patch finds those orphaned entries and updates them to point
	to the correct merged allocation.
	"""
	
	print("=" * 80)
	print("Fixing Orphaned Leave Ledger Entries for Local Leave")
	print("=" * 80)
	
	# Find orphaned ledger entries (pointing to non-existent allocations)
	orphaned_ledgers = frappe.db.sql("""
		SELECT lle.name, lle.transaction_name, lle.employee, lle.leaves,
		       lle.from_date, lle.to_date, lle.is_carry_forward
		FROM `tabLeave Ledger Entry` lle
		LEFT JOIN `tabLeave Allocation` la ON lle.transaction_name = la.name
		WHERE lle.transaction_type = 'Leave Allocation'
		AND lle.leave_type = 'Local Leave'
		AND lle.docstatus = 1
		AND la.name IS NULL
	""", as_dict=True)
	
	if not orphaned_ledgers:
		print("\n✓ No orphaned ledger entries found.")
		return
	
	print(f"\nFound {len(orphaned_ledgers)} orphaned ledger entries")
	
	fixed_count = 0
	not_found_count = 0
	
	for ledger in orphaned_ledgers:
		# Try to find the correct allocation for this employee and date range
		# Look for an allocation that overlaps with the ledger entry's date range
		correct_allocation = frappe.db.sql("""
			SELECT name
			FROM `tabLeave Allocation`
			WHERE employee = %s
			AND leave_type = 'Local Leave'
			AND docstatus = 1
			AND from_date <= %s
			AND to_date >= %s
			ORDER BY creation DESC
			LIMIT 1
		""", (ledger.employee, ledger.to_date, ledger.from_date), as_dict=True)
		
		if correct_allocation:
			# Update the ledger entry to point to the correct allocation
			frappe.db.sql("""
				UPDATE `tabLeave Ledger Entry`
				SET transaction_name = %s
				WHERE name = %s
			""", (correct_allocation[0].name, ledger.name))
			
			fixed_count += 1
			print(f"  ✓ Fixed {ledger.name}: {ledger.transaction_name} -> {correct_allocation[0].name}")
		else:
			# If no allocation found, try to find any Local Leave allocation for this employee
			any_allocation = frappe.db.sql("""
				SELECT name
				FROM `tabLeave Allocation`
				WHERE employee = %s
				AND leave_type = 'Local Leave'
				AND docstatus = 1
				ORDER BY creation DESC
				LIMIT 1
			""", (ledger.employee,), as_dict=True)
			
			if any_allocation:
				frappe.db.sql("""
					UPDATE `tabLeave Ledger Entry`
					SET transaction_name = %s
					WHERE name = %s
				""", (any_allocation[0].name, ledger.name))
				
				fixed_count += 1
				print(f"  ✓ Fixed {ledger.name}: {ledger.transaction_name} -> {any_allocation[0].name} (using any available allocation)")
			else:
				not_found_count += 1
				print(f"  ⚠ Could not find allocation for {ledger.name} (employee: {ledger.employee})")
	
	frappe.db.commit()
	
	print(f"\n✓ Fixed {fixed_count} ledger entries")
	if not_found_count > 0:
		print(f"  ⚠ Warning: {not_found_count} entries could not be fixed (no allocation found)")
	
	print("=" * 80 + "\n")

