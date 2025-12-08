frappe.listview_settings["Salary Slip"] = {
	onload: function (listview) {
		if (
			!has_common(frappe.user_roles, [
				"Administrator",
				"System Manager",
				"HR Manager",
				"HR User",
			])
		)
			return;

		// Track checked items across all pages
		if (!listview.checked_items_tracker) {
			listview.checked_items_tracker = new Set();
		}

		// Override the checkbox change handler to track items across pages
		const original_on_row_checked = listview.on_row_checked || function() {};
		listview.on_row_checked = function() {
			original_on_row_checked.call(this);
			
			// Update tracker with currently checked items on this page
			const current_page_checked = this.get_checked_items(true);
			const current_page_all = this.data.map(d => d.name);
			
			// Remove items from tracker that are on current page but not checked
			current_page_all.forEach(name => {
				if (!current_page_checked.includes(name)) {
					listview.checked_items_tracker.delete(name);
				}
			});
			
			// Add currently checked items to tracker
			current_page_checked.forEach(name => {
				listview.checked_items_tracker.add(name);
			});
		};

		// Clear tracker when list is refreshed or filters change
		const original_refresh = listview.refresh || function() {};
		listview.refresh = function() {
			// Only clear if filters actually changed (not just page navigation)
			try {
				const current_filters = this.filter_area ? JSON.stringify(this.filter_area.get()) : "";
				if (this._last_filters !== current_filters) {
					listview.checked_items_tracker.clear();
					this._last_filters = current_filters;
				}
			} catch (e) {
				// If filter_area doesn't exist or get() fails, just clear tracker
				listview.checked_items_tracker.clear();
			}
			original_refresh.call(this);
		};

		// Helper function to get all checked items across all pages
		function get_all_checked_items() {
			// Get current page checked items
			const current_checked = listview.get_checked_items(true);
			
			// Update tracker with current page
			current_checked.forEach(name => {
				listview.checked_items_tracker.add(name);
			});
			
			// Return all tracked items
			return Array.from(listview.checked_items_tracker);
		}

		// Add to Actions menu (appears when items are selected)
		listview.page.add_actions_menu_item(__("Send Email"), () => {
			const checked_items = get_all_checked_items();
			if (!checked_items.length) {
				frappe.msgprint(__("Please select the salary slips to email"));
				return;
			}

			// Filter to only submitted salary slips and check for employee emails
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Salary Slip",
					filters: {
						name: ["in", checked_items],
						docstatus: 1,
					},
					fields: ["name", "employee", "employee_name"],
				},
				callback: (r) => {
					if (r.exc) {
						frappe.msgprint(__("Error checking salary slip status"));
						return;
					}

					const submitted_slips = r.message.map((doc) => doc.name);
					const unsubmitted_slips = checked_items.filter(
						(name) => !submitted_slips.includes(name)
					);

					if (unsubmitted_slips.length > 0) {
						frappe.msgprint(
							__(
								"Only submitted salary slips can be emailed. {0} selected slip(s) are not submitted.",
								[unsubmitted_slips.length]
							)
						);
					}

					if (submitted_slips.length === 0) {
						frappe.msgprint(__("No submitted salary slips selected"));
						return;
					}

					// Check if employees have email addresses
					const employee_ids = [...new Set(r.message.map((doc) => doc.employee))];
					frappe.call({
						method: "frappe.client.get_list",
						args: {
							doctype: "Employee",
							filters: {
								name: ["in", employee_ids],
							},
							fields: ["name", "employee_name", "prefered_email"],
						},
						callback: (emp_r) => {
							if (emp_r.exc) {
								// Continue anyway if check fails
								proceed_with_email(submitted_slips);
								return;
							}

							const employees_without_email = emp_r.message.filter(
								(emp) => !emp.prefered_email
							);

							if (employees_without_email.length > 0) {
								const employee_names = employees_without_email
									.map((emp) => emp.employee_name || emp.name)
									.join(", ");
								frappe.confirm(
									__(
										"{0} employee(s) do not have email addresses set: {1}. Emails will not be sent for these employees. Do you want to continue?",
										[employees_without_email.length, employee_names]
									),
									() => {
										proceed_with_email(submitted_slips);
									}
								);
							} else {
								proceed_with_email(submitted_slips);
							}
						},
					});

					function proceed_with_email(slip_names) {
						frappe.confirm(
							__("Are you sure you want to email {0} selected salary slip(s)?", [
								slip_names.length,
							]),
							() => {
								frappe.call({
									method: "hrms.payroll.doctype.salary_slip.salary_slip.enqueue_email_salary_slips",
									args: {
										names: slip_names,
									},
									freeze: true,
									freeze_message: __("Emailing Salary Slips..."),
									callback: (result) => {
										if (result.exc) {
											frappe.msgprint({
												title: __("Error"),
												indicator: "red",
												message: __("Error enqueueing salary slip emails. Please check Error Log for details."),
											});
										} else {
											// Clear checked items tracker after successful submission
											listview.checked_items_tracker.clear();
											listview.clear_checked_items();
										}
									},
								});
							}
						);
					}
				},
			});
		});
	},
};
