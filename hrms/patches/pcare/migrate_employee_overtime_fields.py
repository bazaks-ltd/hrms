import frappe

def execute():
    frappe.db.sql("""
        UPDATE `tabEmployee Overtime`
        SET from_time = `from`
        WHERE `from` IS NOT NULL AND (from_time IS NULL)
    """)

    frappe.db.sql("""
        UPDATE `tabEmployee Overtime`
        SET to_time = `to`
        WHERE `to` IS NOT NULL AND (to_time IS NULL)
    """)

    columns = frappe.db.get_table_columns("Employee Overtime")
    if "from" in columns:
        frappe.db.sql_ddl("ALTER TABLE `tabEmployee Overtime` DROP COLUMN `from`")
    if "to" in columns:
        frappe.db.sql_ddl("ALTER TABLE `tabEmployee Overtime` DROP COLUMN `to`")
    frappe.db.commit()
    print("Migrated data from 'from' and 'to' to 'from_time' and 'to_time', and dropped old columns.")