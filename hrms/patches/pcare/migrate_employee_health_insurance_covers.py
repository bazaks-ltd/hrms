import frappe
from frappe.utils import cint


def execute():
	drop_unique_indexes()
	backfill_employee_name()
	close_covers_for_leavers()
	backfill_catastrophe_cover()
	rename_covers()
	update_naming_series()


def drop_unique_indexes():
	table = "tabEmployee Health Insurance"
	for index_name in ("employee", "health_insurance_name"):
		rows = frappe.db.sql(
			f"SHOW INDEX FROM `{table}` WHERE Key_name=%s",
			index_name,
			as_dict=True,
		)
		if rows and not cint(rows[0].Non_unique):
			frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP INDEX `{index_name}`")

	if not frappe.db.has_index(table, "employee"):
		frappe.db.add_index("Employee Health Insurance", ["employee"], index_name="employee")


def backfill_employee_name():
	frappe.db.sql(
		"""
		UPDATE `tabEmployee Health Insurance` ehi
		INNER JOIN `tabEmployee` e ON e.name = ehi.employee
		SET ehi.employee_name = e.employee_name
		WHERE IFNULL(ehi.employee_name, '') = ''
		"""
	)

	columns = frappe.db.get_table_columns("Employee Health Insurance")
	if "custom_employee_name" in columns:
		frappe.db.sql(
			"""
			UPDATE `tabEmployee Health Insurance`
			SET employee_name = custom_employee_name
			WHERE IFNULL(employee_name, '') = ''
				AND IFNULL(custom_employee_name, '') != ''
			"""
		)


def close_covers_for_leavers():
	frappe.db.sql(
		"""
		UPDATE `tabEmployee Health Insurance` ehi
		INNER JOIN `tabEmployee` e ON e.name = ehi.employee
		SET ehi.is_active = 0,
			ehi.valid_upto = COALESCE(ehi.valid_upto, e.relieving_date)
		WHERE e.status = 'Left'
		"""
	)


def backfill_catastrophe_cover():
	frappe.db.sql(
		"""
		UPDATE `tabEmployee Health Insurance`
		SET catastrophe_cover = 1
		WHERE IFNULL(insurance_catastrophe_cover, 0) > 0
			OR IFNULL(dependent_catastrophe_cover, 0) > 0
		"""
	)


def rename_covers():
	"""Rename in SQL so we do not scan every Link field via rename_doc."""
	frappe.db.sql(
		"""
		UPDATE `tabInsurance Dependent`
		SET parent = CONCAT('EHI-', parent, '-00001')
		WHERE parenttype = 'Employee Health Insurance'
			AND parent NOT LIKE 'EHI-%'
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabVersion`
		SET docname = CONCAT('EHI-', docname, '-00001')
		WHERE ref_doctype = 'Employee Health Insurance'
			AND docname NOT LIKE 'EHI-%'
		"""
	)
	if frappe.db.table_exists("File"):
		frappe.db.sql(
			"""
			UPDATE `tabFile`
			SET attached_to_name = CONCAT('EHI-', attached_to_name, '-00001')
			WHERE attached_to_doctype = 'Employee Health Insurance'
				AND attached_to_name NOT LIKE 'EHI-%'
			"""
		)
	frappe.db.sql(
		"""
		UPDATE `tabEmployee Health Insurance`
		SET name = CONCAT('EHI-', employee, '-00001')
		WHERE name NOT LIKE 'EHI-%'
		"""
	)


def update_naming_series():
	covers = frappe.db.sql(
		"""
		SELECT name, employee
		FROM `tabEmployee Health Insurance`
		""",
		as_dict=True,
	)
	max_by_prefix = {}
	for cover in covers:
		if not cover.employee:
			continue
		prefix = f"EHI-{cover.employee}-"
		if not str(cover.name).startswith(prefix):
			continue
		suffix = str(cover.name)[len(prefix) :]
		if suffix.isdigit():
			max_by_prefix[prefix] = max(max_by_prefix.get(prefix, 0), cint(suffix))

	for prefix, current in max_by_prefix.items():
		frappe.db.sql(
			"""
			INSERT INTO `tabSeries` (`name`, `current`)
			VALUES (%s, %s)
			ON DUPLICATE KEY UPDATE `current` = GREATEST(`current`, VALUES(`current`))
			""",
			(prefix, current),
		)
