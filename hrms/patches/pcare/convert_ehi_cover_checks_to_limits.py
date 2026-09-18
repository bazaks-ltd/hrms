import frappe


def execute():
	"""Turn Inpatient/Outpatient cover flags into currency limits."""
	table = "tabEmployee Health Insurance"
	for fieldname in ("inpatient_cover", "outpatient_cover"):
		col = frappe.db.sql(
			"""
			SELECT DATA_TYPE
			FROM information_schema.COLUMNS
			WHERE TABLE_SCHEMA = DATABASE()
				AND TABLE_NAME = %s
				AND COLUMN_NAME = %s
			""",
			(table, fieldname),
			as_dict=True,
		)
		if not col:
			continue
		if (col[0].DATA_TYPE or "").lower() in ("tinyint", "int", "smallint"):
			frappe.db.sql_ddl(
				f"""
				ALTER TABLE `{table}`
				MODIFY `{fieldname}` decimal(21,9) NOT NULL DEFAULT 0.000000000
				"""
			)
			frappe.db.sql(
				f"""
				UPDATE `{table}`
				SET `{fieldname}` = 0
				WHERE `{fieldname}` IN (0, 1)
				"""
			)

	if "catastrophe_cover" in frappe.db.get_table_columns("Employee Health Insurance"):
		# leftover Yes/No flag; amounts live on insurance_catastrophe_cover
		frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `catastrophe_cover`")
