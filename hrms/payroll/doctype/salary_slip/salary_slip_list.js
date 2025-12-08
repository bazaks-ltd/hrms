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

			// Filter to only submitted salary slips
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Salary Slip",
					filters: {
						name: ["in", checked_items],
						docstatus: 1,
					},
					fields: ["name"],
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

					frappe.confirm(
						__("Are you sure you want to email {0} selected salary slip(s)?", [
							submitted_slips.length,
						]),
						() => {
							frappe.call({
								method: "hrms.payroll.doctype.salary_slip.salary_slip.enqueue_email_salary_slips",
								args: {
									names: submitted_slips,
								},
								freeze: true,
								freeze_message: __("Emailing Salary Slips..."),
							});
						}
					);
				},
			});
		});
	},
};
