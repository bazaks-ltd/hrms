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

		// Add to Actions menu (appears when items are selected)
		listview.page.add_actions_menu_item(__("Send Email"), () => {
			const checked_items = listview.get_checked_items(true);
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
