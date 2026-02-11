// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("MO Leave Control Panel", {
	setup: function (frm) {
		frm.trigger("set_defaults");
		hrms.setup_employee_filter_group(frm);
	},

	refresh: function (frm) {
		frm.page.clear_indicator();
		frm.disable_save();
		frm.trigger("get_employees");
		frm.trigger("set_primary_action");
		frm.trigger("add_scheduler_buttons");
		hrms.handle_realtime_bulk_action_notification(
			frm,
			"completed_bulk_mo_leave_policy_assignment",
			"MO Leave Policy Assignment"
		);
	},

	set_defaults: function (frm) {
		if (!frm.doc.from_date) {
			// Set to beginning of current year
			const today = frappe.datetime.get_today();
			const year = today.split("-")[0];
			frm.set_value("from_date", `${year}-01-01`);
		}
		if (!frm.doc.to_date) {
			// Set to end of current year
			const today = frappe.datetime.get_today();
			const year = today.split("-")[0];
			frm.set_value("to_date", `${year}-12-31`);
		}
		// Ensure dates are always beginning and end of year
		if (frm.doc.from_date) {
			const fromDate = new Date(frm.doc.from_date);
			const yearStart = new Date(fromDate.getFullYear(), 0, 1);
			if (frappe.datetime.obj_to_str(fromDate) !== frappe.datetime.obj_to_str(yearStart)) {
				frm.set_value("from_date", frappe.datetime.obj_to_str(yearStart));
			}
		}
		if (frm.doc.to_date) {
			const toDate = new Date(frm.doc.to_date);
			const yearEnd = new Date(toDate.getFullYear(), 11, 31);
			if (frappe.datetime.obj_to_str(toDate) !== frappe.datetime.obj_to_str(yearEnd)) {
				frm.set_value("to_date", frappe.datetime.obj_to_str(yearEnd));
			}
		}
		if (!frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_default("company"));
		}
	},

	company: function (frm) {
		if (frm.doc.company) {
			frm.set_query("department", function () {
				return {
					filters: {
						company: frm.doc.company,
					},
				};
			});
		}
		frm.trigger("get_employees");
	},

	employment_type(frm) {
		frm.trigger("get_employees");
	},

	branch(frm) {
		frm.trigger("get_employees");
	},

	department(frm) {
		frm.trigger("get_employees");
	},

	designation(frm) {
		frm.trigger("get_employees");
	},

	employee_grade(frm) {
		frm.trigger("get_employees");
	},

	tenure_filter(frm) {
		frm.trigger("get_employees");
	},

	from_date(frm) {
		// Ensure from_date is always beginning of year
		if (frm.doc.from_date) {
			const fromDate = new Date(frm.doc.from_date);
			const yearStart = new Date(fromDate.getFullYear(), 0, 1);
			if (frappe.datetime.obj_to_str(fromDate) !== frappe.datetime.obj_to_str(yearStart)) {
				frm.set_value("from_date", frappe.datetime.obj_to_str(yearStart));
			}
		}
		frm.trigger("get_employees");
	},

	to_date(frm) {
		// Ensure to_date is always end of year
		if (frm.doc.to_date) {
			const toDate = new Date(frm.doc.to_date);
			const yearEnd = new Date(toDate.getFullYear(), 11, 31);
			if (frappe.datetime.obj_to_str(toDate) !== frappe.datetime.obj_to_str(yearEnd)) {
				frm.set_value("to_date", frappe.datetime.obj_to_str(yearEnd));
			}
		}
		frm.trigger("get_employees");
	},

	get_employees(frm) {
		frm.call({
			method: "get_employees",
			args: {
				advanced_filters: frm.advanced_filters || [],
			},
			doc: frm.doc,
		}).then((r) => {
			const columns = frm.events.get_employees_datatable_columns();
			hrms.render_employees_datatable(
				frm,
				columns,
				r.message,
				__("No Data"),
				null,
				{
					onCheckRow: () => {
						frm.trigger("update_selected_count");
					},
				}
			);
			frm.trigger("update_selected_count");
		});
	},

	update_selected_count(frm) {
		if (!frm.employees_datatable) return;

		const check_map = frm.employees_datatable.rowmanager.checkMap;
		const selected_count = check_map.filter((is_checked) => is_checked).length;

		// Update primary action button to show count
		if (selected_count > 0) {
			frm.page.set_primary_action(
				__("Allocate MO Leaves ({0})", [selected_count]),
				() => {
					frm.trigger("allocate_mo_leaves");
				}
			);
		} else {
			frm.page.set_primary_action(__("Allocate MO Leaves"), () => {
				frm.trigger("allocate_mo_leaves");
			});
		}

		// Update visual indicator in employees section
		const $employees_wrapper = frm.get_field("employees_html").$wrapper;
		let $count_indicator = $employees_wrapper.find(".selected-count-indicator");
		
		if (selected_count > 0) {
			if ($count_indicator.length === 0) {
				$count_indicator = $(
					`<div class="selected-count-indicator" style="padding: 10px; background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 4px; margin-bottom: 10px;">
						<strong>${__("Selected Employees")}: <span class="selected-count">0</span></strong>
					</div>`
				).prependTo($employees_wrapper);
			}
			$count_indicator.find(".selected-count").text(selected_count);
			$count_indicator.show();
		} else {
			if ($count_indicator.length > 0) {
				$count_indicator.hide();
			}
		}
	},

	get_employees_datatable_columns() {
		return [
			{
				name: "employee",
				id: "employee",
				content: __("Employee"),
			},
			{
				name: "employee_name",
				id: "employee_name",
				content: __("Name"),
			},
			{
				name: "company",
				id: "company",
				content: __("Company"),
			},
			{
				name: "department",
				id: "department",
				content: __("Department"),
			},
		].map((x) => ({
			...x,
			editable: false,
			focusable: false,
			dropdown: false,
			align: "left",
		}));
	},

	set_primary_action(frm) {
		frm.page.set_primary_action(__("Allocate MO Leaves"), () => {
			frm.trigger("allocate_mo_leaves");
		});
	},

	allocate_mo_leaves(frm) {
		const check_map = frm.employees_datatable.rowmanager.checkMap;
		const selected_employees = [];
		check_map.forEach((is_checked, idx) => {
			if (is_checked)
				selected_employees.push(frm.employees_datatable.datamanager.data[idx].employee);
		});

		hrms.validate_mandatory_fields(frm, selected_employees);

		if (selected_employees.length === 0) {
			frappe.msgprint(__("Please select at least one employee"));
			return;
		}

		frappe.confirm(
			__("Allocate MO leaves to {0} employee(s)?", [selected_employees.length]),
			() => frm.events.bulk_allocate_mo_leaves(frm, selected_employees)
		);
	},

	bulk_allocate_mo_leaves(frm, employees) {
		frm.call({
			method: "allocate_mo_leaves",
			doc: frm.doc,
			args: {
				employees: employees,
			},
			freeze: true,
			freeze_message: __("Allocating MO Leaves"),
		}).then((r) => {
			if (r.message.failure && r.message.failure.length > 0) {
				// Show detailed error messages
				const failed_employees = r.message.failure
					.map((f) => {
						if (typeof f === "object" && f.error) {
							// Clean up error message - remove "Reference:" prefix if present
							let error_msg = f.error;
							if (error_msg.includes("Reference:")) {
								// Extract the actual error before "Reference:"
								const ref_index = error_msg.indexOf("Reference:");
								if (ref_index > 0) {
									error_msg = error_msg.substring(0, ref_index).trim();
								}
							}
							return `<strong>${f.employee}</strong>: ${error_msg}`;
						}
						return typeof f === "string" ? f : JSON.stringify(f);
					})
					.join("<br><br>");

				frappe.msgprint({
					title: __("Allocation Failed"),
					message: __("Failed to create/submit MO Leave Policy Assignment for the following employees:<br><br>{0}", [
						failed_employees,
					]),
					indicator: "red",
					is_minimizable: true,
				});
			}

			if (r.message.success && r.message.success.length > 0) {
				frappe.show_alert({
					message: __("{0} employee(s) processed successfully", [r.message.success.length]),
					indicator: "green",
				});
			}

			// don't refresh on complete failure
			if (r.message.failure && r.message.failure.length > 0 && (!r.message.success || r.message.success.length === 0)) return;
			frm.refresh();
		});
	},

	add_scheduler_buttons(frm) {
		// Add button to manually trigger daily scheduler for testing
		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Run Daily Scheduler"),
			function () {
				frappe.confirm(
					__(
						"This will run the daily scheduler to allocate leaves for employees who crossed 6 months or 12 months thresholds. Continue?"
					),
					function () {
						// Yes
						frappe.call({
							method: "run_daily_scheduler_manual",
							doc: frm.doc,
							freeze: true,
							freeze_message: __("Running daily scheduler..."),
						}).then((r) => {
							if (r.message) {
								const result = r.message;
								const success = result.success || [];
								const failure = result.failure || [];
								const skipped = result.skipped;

								if (skipped) {
									frappe.show_alert({
										message: __("Scheduler skipped: {0}", [skipped]),
										indicator: "blue",
									});
								} else if (success.length > 0 || failure.length > 0) {
									let message = __(
										"Processed {0} employees successfully",
										[success.length]
									);
									if (failure.length > 0) {
										message += __(", {0} failed", [failure.length]);
									}
									frappe.show_alert({
										message: message,
										indicator: failure.length > 0 ? "orange" : "green",
									});
								} else {
									frappe.show_alert({
										message: __("No employees processed"),
										indicator: "blue",
									});
								}
							}
						});
					},
					function () {
						// No
					}
				);
			},
			__("Testing")
		);
	},

});
