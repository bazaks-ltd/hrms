// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

var in_progress = false;

frappe.provide("erpnext.accounts.dimensions");

frappe.ui.form.on("Payroll Entry", {
	onload: function (frm) {
		frm.ignore_doctypes_on_cancel_all = ["Salary Slip", "Journal Entry"];

		if (!frm.doc.posting_date) {
			frm.doc.posting_date = frappe.datetime.nowdate();
		}
		frm.toggle_reqd(["payroll_frequency"], !frm.doc.salary_slip_based_on_timesheet);

		erpnext.accounts.dimensions.setup_dimension_filters(frm, frm.doctype);
		frm.events.department_filters(frm);
		frm.events.payroll_payable_account_filters(frm);

		frappe.realtime.off("completed_salary_slip_creation");
		frappe.realtime.on("completed_salary_slip_creation", function () {
			frm.reload_doc();
		});

		frappe.realtime.off("completed_salary_slip_submission");
		frappe.realtime.on("completed_salary_slip_submission", function () {
			frm.reload_doc();
		});
	},

	department_filters: function (frm) {
		frm.set_query("department", function () {
			return {
				filters: {
					company: frm.doc.company,
				},
			};
		});
	},

	payroll_payable_account_filters: function (frm) {
		frm.set_query("payroll_payable_account", function () {
			return {
				filters: {
					company: frm.doc.company,
					root_type: "Liability",
					is_group: 0,
				},
			};
		});
	},

	refresh: function (frm) {
		if (frm.doc.status === "Queued") frm.page.btn_secondary.hide();

		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.page.clear_primary_action();
			frm.add_custom_button(__("Get Employees"), function () {
				frm.events.get_employee_details(frm);
			}).toggleClass("btn-primary", !(frm.doc.employees || []).length);
		}

		if (
			(frm.doc.employees || []).length &&
			!frappe.model.has_workflow(frm.doctype) &&
			!cint(frm.doc.salary_slips_created) &&
			frm.doc.docstatus != 2
		) {
			if (frm.doc.docstatus == 0 && !frm.is_new()) {
				frm.page.clear_primary_action();
				frm.page.set_primary_action(__("Create Salary Slips"), () => {
					frm.save("Submit").then(() => {
						frm.page.clear_primary_action();
						frm.refresh();
					});
				});
			} else if (frm.doc.docstatus == 1 && frm.doc.status == "Failed") {
				frm.add_custom_button(__("Create Salary Slips"), function () {
					frm.call("create_salary_slips");
				}).addClass("btn-primary");
			}
		}

		if (frm.doc.docstatus == 1) {
			if (frm.custom_buttons) frm.clear_custom_buttons();
			frm.events.add_context_buttons(frm);
		}

		if (frm.doc.status == "Failed" && frm.doc.error_message) {
			const issue = `<a id="jump_to_error" style="text-decoration: underline;">issue</a>`;
			let process = cint(frm.doc.salary_slips_created) ? "submission" : "creation";

			frm.dashboard.set_headline(
				__("Salary Slip {0} failed. You can resolve the {1} and retry {0}.", [
					process,
					issue,
				])
			);

			$("#jump_to_error").on("click", (e) => {
				e.preventDefault();
				frm.scroll_to_field("error_message");
			});
		}

		if (!frm.is_new()) {
			frm.events.render_payslips_review(frm);
		}
	},

	get_employee_details: function (frm) {
		return frappe
			.call({
				doc: frm.doc,
				method: "fill_employee_details",
				freeze: true,
				freeze_message: __("Fetching Employees"),
			})
			.then((r) => {
				if (r.docs?.[0]?.employees) {
					frm.dirty();
					frm.save();
				}

				frm.refresh();

				if (r.docs?.[0]?.validate_attendance) {
					render_employee_attendance(frm, r.message);
				}
				frm.scroll_to_field("employees");
			});
	},

	create_salary_slips: function (frm) {
		frm.call({
			doc: frm.doc,
			method: "run_doc_method",
			args: {
				method: "create_salary_slips",
				dt: "Payroll Entry",
				dn: frm.doc.name,
			},
		});
	},

	add_context_buttons: function (frm) {
		const slips_submitted =
			frm.doc.salary_slips_submitted ||
			(frm.doc.__onload && frm.doc.__onload.submitted_ss);

		if (frm.doc.status === "Completed") {
			if (frm.doc.__onload && frm.doc.__onload.submitted_je) {
				frm.events.add_submit_mra_button(frm);
			}
		} else if (slips_submitted) {
			frm.events.add_complete_btn(frm);
		} else if (cint(frm.doc.salary_slips_created)) {
			frm.add_custom_button(__("Submit Salary Slip"), function () {
				submit_salary_slip(frm);
			}).addClass("btn-primary");
		} else if (!frm.doc.salary_slips_created && frm.doc.status === "Failed") {
			frm.add_custom_button(__("Create Salary Slips"), function () {
				frm.trigger("create_salary_slips");
			}).addClass("btn-primary");
		}

		// Always show Email Slips button (it will only email submitted salary slips)
		if (!frm.is_new()) {
			frm.events.add_email_slips_btn(frm);
		}
	},

	add_complete_btn: function (frm) {
		frm.add_custom_button(__("Complete"), function () {
			if (!frm.doc.payment_account && !frm.doc.cheque_payment_account) {
				frappe.msgprint({
					message: __(
						"Set Cheque Payment Account or Payment Account before Completing."
					),
					indicator: "orange",
					title: __("Payment Account Required"),
				});
				frm.scroll_to_field(
					frm.doc.cheque_payment_account ? "payment_account" : "cheque_payment_account"
				);
				return;
			}

			frappe.call({
				doc: frm.doc,
				method: "mark_complete",
				freeze: true,
				freeze_message: __("Completing Payroll Entry..."),
				callback: function () {
					frm.reload_doc();
				},
			});
		}).addClass("btn-primary");
	},

	render_payslips_review: function (frm) {
		if (!frm.fields_dict.payslips_review_html) {
			return;
		}

		frappe.call({
			doc: frm.doc,
			method: "get_payslips_for_review",
			callback: function (r) {
				if (!r.message) {
					return;
				}
				const data = r.message;
				frm._payroll_modes_of_payment = data.modes_of_payment || [];
				frm.fields_dict.payslips_review_html.$wrapper.html(
					frappe.render_template("payroll_payslips_review", data)
				);
				frm.events.bind_payslips_review_events(frm);
			},
		});
	},

	bind_payslips_review_events: function (frm) {
		const $wrap = frm.fields_dict.payslips_review_html.$wrapper;

		frm.events.bind_payslips_search_filters(frm, $wrap);

		$wrap.find(".payroll-use-cheque-btn").off("click").on("click", function () {
			frappe.call({
				doc: frm.doc,
				method: "set_payment_account",
				args: { use_cheque: 1 },
				freeze: true,
				callback: function () {
					frm.reload_doc();
				},
			});
		});

		$wrap.find(".payroll-change-payment-account-btn").off("click").on("click", function () {
			frm.events.prompt_payment_account(frm, frm.doc.payment_account, function (payment_account) {
				frappe.call({
					doc: frm.doc,
					method: "set_payment_account",
					args: { payment_account: payment_account, use_cheque: 0 },
					freeze: true,
					callback: function () {
						frm.reload_doc();
					},
				});
			});
		});

		$wrap.find(".payroll-change-all-mop-btn").off("click").on("click", function () {
			frm.events.prompt_mode_of_payment(frm, null, function (mode_of_payment) {
				frappe.call({
					doc: frm.doc,
					method: "set_all_salary_slip_mode_of_payment",
					args: { mode_of_payment: mode_of_payment },
					freeze: true,
					callback: function () {
						frm.reload_doc();
					},
				});
			}, __("Change All Modes of Payment"));
		});

		$wrap.find(".payroll-change-bank-ref-btn").off("click").on("click", function () {
			frm.events.prompt_reference_no(
				frm,
				frm.doc.bank_entry_reference_no,
				function (reference_no) {
					frappe.call({
						doc: frm.doc,
						method: "set_bank_entry_reference_no",
						args: { bank_entry_reference_no: reference_no },
						freeze: true,
						callback: function () {
							frm.reload_doc();
						},
					});
				},
				__("Bank Entry Reference No"),
				false
			);
		});

		$wrap
			.find(".payroll-change-slip-mop-btn")
			.off("click")
			.on("click", function () {
				const salary_slip = $(this).data("salary-slip");
				const current_mop = $(this).data("mode-of-payment");
				frm.events.prompt_mode_of_payment(
					frm,
					current_mop,
					function (mode_of_payment) {
						frappe.call({
							doc: frm.doc,
							method: "set_salary_slip_mode_of_payment",
							args: {
								salary_slip: salary_slip,
								mode_of_payment: mode_of_payment,
							},
							freeze: true,
							callback: function () {
								frm.reload_doc();
							},
						});
					},
					__("Change Mode of Payment")
				);
			});

		$wrap
			.find(".payroll-change-slip-ref-btn")
			.off("click")
			.on("click", function () {
				const salary_slip = $(this).data("salary-slip");
				const current_ref = $(this).data("payment-reference-no");
				const is_cheque = cint($(this).data("is-cheque"));
				frm.events.prompt_reference_no(
					frm,
					current_ref,
					function (reference_no) {
						frappe.call({
							doc: frm.doc,
							method: "set_salary_slip_payment_reference_no",
							args: {
								salary_slip: salary_slip,
								payment_reference_no: reference_no,
							},
							freeze: true,
							callback: function () {
								frm.reload_doc();
							},
						});
					},
					__("Payment Reference No"),
					!!is_cheque
				);
			});

		$wrap.find(".payroll-bulk-je-btn").off("click").on("click", function () {
			frappe.confirm(
				__(
					"This will create one accrual Journal Entry, one bulk bank-transfer Bank Entry, and one Bank Entry per cheque payslip. Continue?"
				),
				function () {
					frappe.call({
						doc: frm.doc,
						method: "bulk_create_journal_entries",
						freeze: true,
						freeze_message: __("Creating Journal Entries..."),
						callback: function (r) {
							frm.reload_doc();
							if (r.message && !r.message.queued) {
								frappe.set_route("List", "Journal Entry", {
									"Journal Entry Account.reference_name": frm.doc.name,
								});
							}
						},
					});
				}
			);
		});
	},

	bind_payslips_search_filters: function (frm, $wrap) {
		const $input = $wrap.find(".payroll-employee-search-input");
		const $hint = $wrap.find(".payroll-payslips-search-hint");
		const $rows = $wrap.find("tr.payroll-payslip-row");
		if (!$rows.length) {
			return;
		}

		const total = $rows.length;

		function apply_payslips_filters() {
			const q = ($input.val() || "").trim().toLowerCase();
			const mop = ($wrap.find(".payroll-mop-filter .active").data("mode-of-payment") || "") + "";
			let visible = 0;

			$rows.each(function () {
				const $r = $(this);
				const employee = (($r.attr("data-employee") || "") + "").toLowerCase();
				const employee_name = (($r.attr("data-employee-name") || "") + "").toLowerCase();
				const row_mop = ($r.attr("data-mode-of-payment") || "") + "";
				const match_text = !q || employee.indexOf(q) !== -1 || employee_name.indexOf(q) !== -1;
				const match_mop =
					!mop ||
					(mop === "__not_set__" ? !row_mop : row_mop === mop);
				const match = match_text && match_mop;
				$r.toggle(match);
				if (match) {
					visible += 1;
				}
			});

			if (!q && !mop) {
				$hint.text("");
				return;
			}

			const filter_parts = [];
			if (q) {
				filter_parts.push(__("employee"));
			}
			if (mop === "__not_set__") {
				filter_parts.push(__("Mode of Payment not set"));
			} else if (mop) {
				filter_parts.push(mop);
			}
			$hint.text(
				__("{0} of {1} payslips match ({2})", [visible, total, filter_parts.join(", ")])
			);
		}

		$input.off("input.payrollPayslipsFilter").on("input.payrollPayslipsFilter", apply_payslips_filters);
		$wrap
			.find(".payroll-mop-filter button")
			.off("click.payrollPayslipsFilter")
			.on("click.payrollPayslipsFilter", function () {
				$wrap.find(".payroll-mop-filter button").removeClass("active");
				$(this).addClass("active");
				apply_payslips_filters();
			});
	},

	prompt_payment_account: function (frm, default_account, callback) {
		frappe.prompt(
			[
				{
					fieldname: "payment_account",
					fieldtype: "Link",
					label: __("Payment Account"),
					options: "Account",
					reqd: 1,
					default: default_account,
					get_query: function () {
						return {
							filters: {
								account_type: ["in", ["Bank", "Cash"]],
								is_group: 0,
								company: frm.doc.company,
							},
						};
					},
				},
			],
			function (values) {
				callback(values.payment_account);
			},
			__("Change Payment Account"),
			__("Update")
		);
	},

	prompt_reference_no: function (frm, default_value, callback, title, reqd) {
		frappe.prompt(
			[
				{
					fieldname: "reference_no",
					fieldtype: "Data",
					label: title || __("Reference No"),
					reqd: cint(reqd),
					default: default_value || "",
				},
			],
			function (values) {
				callback(values.reference_no);
			},
			title || __("Reference No"),
			__("Update")
		);
	},

	prompt_mode_of_payment: function (frm, default_mode, callback, title) {
		if (!frm.doc.payment_account) {
			frappe.msgprint({
				title: __("Payment Account Required"),
				message: __("Set Payment Account on Payroll Entry before assigning Mode of Payment."),
				indicator: "orange",
			});
			return;
		}

		const show_dialog = function (modes) {
			if (!modes.length) {
				frappe.msgprint({
					title: __("No Mode of Payment"),
					message: __(
						"No Mode of Payment is linked to payment account {0} for company {1}.",
						[frm.doc.payment_account, frm.doc.company]
					),
					indicator: "red",
				});
				return;
			}

			const d = new frappe.ui.Dialog({
				title: title || __("Change Mode of Payment"),
				fields: [
					{
						label: __("Mode of Payment"),
						fieldname: "mode_of_payment",
						fieldtype: "Select",
						options: modes.join("\n"),
						reqd: 1,
						default:
							default_mode && modes.indexOf(default_mode) !== -1
								? default_mode
								: modes.length === 1
									? modes[0]
									: "",
					},
				],
				primary_action_label: __("Update"),
				primary_action(values) {
					if (!values.mode_of_payment) {
						frappe.msgprint(__("Mode of Payment is required"));
						return;
					}
					d.hide();
					callback(values.mode_of_payment);
				},
			});
			d.show();
		};

		if (frm._payroll_modes_of_payment && frm._payroll_modes_of_payment.length) {
			show_dialog(frm._payroll_modes_of_payment);
			return;
		}

		frappe.call({
			doc: frm.doc,
			method: "get_modes_of_payment",
			callback: function (r) {
				const modes = (r.message && r.message.modes_of_payment) || [];
				frm._payroll_modes_of_payment = modes;
				show_dialog(modes);
			},
		});
	},

	add_bank_entry_button: function (frm) {
		if (frm.doc.submitted_bank || frm.doc.status !== "Completed" || !cint(frm.doc.payslips_reviewed)) {
			return;
		}
		frm.add_custom_button(__("Make Bank Entry"), function () {
			make_bank_entry(frm);
		}).addClass("btn-primary");
	},

	add_submit_mra_button: function (frm) {
		if (frm.doc.submitted_mra) {
			return;
		}
		frm.add_custom_button(__("Submit MRA"), function () {
			frappe.call({
				method: "run_doc_method",
				args: {
					method: "submit_mra",
					dt: "Payroll Entry",
					dn: frm.doc.name,
				},
				callback: function () {
					frappe.set_route("List", "Journal Entry", {
						"Journal Entry Account.reference_name": frm.doc.name,
					});
				},
				freeze: true,
				freeze_message: __("Creating Payment Entries......"),
			});
		}).addClass("btn-primary");
	},

	add_submit_journal_entry_btn: function (frm) {
		// Journal entries are created via Payslips tab after Complete + review
		return;
	},

	add_email_slips_btn: function (frm) {
		frm.add_custom_button(__("Email Slips"), function () {
			frappe.call({
				method: "run_doc_method",
				args: {
					method: "email_slips",
					dt: "Payroll Entry",
					dn: frm.doc.name,
				},
				callback: function () {
					frappe.dom.unfreeze();
				},
				freeze: true,
				freeze_message: __("Emailing Slips ......"),
			});
		});
	},

	cheque_payment_account: function (frm) {
		if (frm.doc.cheque_payment_account && !frm.doc.payment_account) {
			frm.set_value("payment_account", frm.doc.cheque_payment_account);
		}
	},

	setup: function (frm) {
		frm.add_fetch("company", "cost_center", "cost_center");

		frm.set_query("payment_account", function () {
			var account_types = ["Bank", "Cash"];
			return {
				filters: {
					account_type: ["in", account_types],
					is_group: 0,
					company: frm.doc.company,
				},
			};
		});

		frm.set_query("cheque_payment_account", function () {
			return {
				filters: {
					account_type: ["in", ["Bank", "Cash"]],
					is_group: 0,
					company: frm.doc.company,
				},
			};
		});

		frm.set_query("employee", "employees", () => {
			let error_fields = [];
			let mandatory_fields = ["company", "payroll_frequency", "start_date", "end_date"];

			let message = __("Mandatory fields required in {0}", [__(frm.doc.doctype)]);

			mandatory_fields.forEach((field) => {
				if (!frm.doc[field]) {
					error_fields.push(frappe.unscrub(field));
				}
			});

			if (error_fields && error_fields.length) {
				message = message + "<br><br><ul><li>" + error_fields.join("</li><li>") + "</ul>";
				frappe.throw({
					message: message,
					indicator: "red",
					title: __("Missing Fields"),
				});
			}

			return {
				query: "hrms.payroll.doctype.payroll_entry.payroll_entry.employee_query",
				filters: frm.events.get_employee_filters(frm),
			};
		});
	},

	get_employee_filters: function (frm) {
		let filters = {};

		let fields = [
			"company",
			"start_date",
			"end_date",
			"payroll_frequency",
			"payroll_payable_account",
			"currency",
			"department",
			"branch",
			"designation",
			"salary_slip_based_on_timesheet",
			"grade",
		];

		fields.forEach((field) => {
			if (frm.doc[field] || frm.doc[field] === 0) {
				filters[field] = frm.doc[field];
			}
		});

		if (frm.doc.employees) {
			let employees = frm.doc.employees.filter((d) => d.employee).map((d) => d.employee);
			if (employees && employees.length) {
				filters["employees"] = employees;
			}
		}
		return filters;
	},

	payroll_frequency: function (frm) {
		frm.trigger("set_start_end_dates").then(() => {
			frm.events.clear_employee_table(frm);
		});
	},

	company: function (frm) {
		frm.events.clear_employee_table(frm);
		erpnext.accounts.dimensions.update_dimension(frm, frm.doctype);
		frm.trigger("set_payable_account_and_currency");
	},

	set_payable_account_and_currency: function (frm) {
		frappe.db.get_value("Company", { name: frm.doc.company }, "default_currency", (r) => {
			frm.set_value("currency", r.default_currency);
		});
		frappe.db.get_value(
			"Company",
			{ name: frm.doc.company },
			"default_payroll_payable_account",
			(r) => {
				frm.set_value("payroll_payable_account", r.default_payroll_payable_account);
			}
		);
	},

	currency: function (frm) {
		var company_currency;
		if (!frm.doc.company) {
			company_currency = erpnext.get_currency(frappe.defaults.get_default("Company"));
		} else {
			company_currency = erpnext.get_currency(frm.doc.company);
		}
		if (frm.doc.currency) {
			if (company_currency != frm.doc.currency) {
				frappe.call({
					method: "erpnext.setup.utils.get_exchange_rate",
					args: {
						from_currency: frm.doc.currency,
						to_currency: company_currency,
					},
					callback: function (r) {
						frm.set_value("exchange_rate", flt(r.message));
						frm.set_df_property("exchange_rate", "hidden", 0);
						frm.set_df_property(
							"exchange_rate",
							"description",
							"1 " + frm.doc.currency + " = [?] " + company_currency
						);
					},
				});
			} else {
				frm.set_value("exchange_rate", 1.0);
				frm.set_df_property("exchange_rate", "hidden", 1);
				frm.set_df_property("exchange_rate", "description", "");
			}
		}
	},

	department: function (frm) {
		frm.events.clear_employee_table(frm);
	},
	grade: function (frm) {
		frm.events.clear_employee_table(frm);
	},
	designation: function (frm) {
		frm.events.clear_employee_table(frm);
	},

	branch: function (frm) {
		frm.events.clear_employee_table(frm);
	},

	start_date: function (frm) {
		if (!in_progress && frm.doc.start_date) {
			frm.trigger("set_end_date");
		} else {
			// reset flag
			in_progress = false;
		}
		frm.events.clear_employee_table(frm);
	},

	project: function (frm) {
		frm.events.clear_employee_table(frm);
	},

	salary_slip_based_on_timesheet: function (frm) {
		frm.toggle_reqd(["payroll_frequency"], !frm.doc.salary_slip_based_on_timesheet);
		hrms.set_payroll_frequency_to_null(frm);
	},

	set_start_end_dates: function (frm) {
		if (!frm.doc.salary_slip_based_on_timesheet) {
			frappe.call({
				method: "hrms.payroll.doctype.payroll_entry.payroll_entry.get_start_end_dates",
				args: {
					payroll_frequency: frm.doc.payroll_frequency,
					start_date: frm.doc.posting_date,
				},
				callback: function (r) {
					if (r.message) {
						in_progress = true;
						frm.set_value("start_date", r.message.start_date);
						frm.set_value("end_date", r.message.end_date);
					}
				},
			});
		}
	},

	set_end_date: function (frm) {
		frappe.call({
			method: "hrms.payroll.doctype.payroll_entry.payroll_entry.get_end_date",
			args: {
				frequency: frm.doc.payroll_frequency,
				start_date: frm.doc.start_date,
			},
			callback: function (r) {
				if (r.message) {
					frm.set_value("end_date", r.message.end_date);
				}
			},
		});
	},

	validate_attendance: function (frm) {
		if (frm.doc.validate_attendance && frm.doc.employees?.length > 0) {
			frappe.call({
				method: "get_employees_with_unmarked_attendance",
				args: {},
				callback: function (r) {
					render_employee_attendance(frm, r.message);
				},
				doc: frm.doc,
				freeze: true,
				freeze_message: __("Validating Employee Attendance..."),
			});
		} else {
			frm.fields_dict.attendance_detail_html.html("");
		}
	},

	clear_employee_table: function (frm) {
		frm.clear_table("employees");
		frm.refresh();
	},
});

// Submit salary slips

const submit_salary_slip = function (frm) {
	frappe.confirm(
		__("This will submit Salary Slips. Do you want to proceed?"),
		function () {
			frappe.call({
				method: "submit_salary_slips",
				args: {},
				doc: frm.doc,
				freeze: true,
				freeze_message: __("Submitting Salary Slips..."),
			});
		},
		function () {
			if (frappe.dom.freeze_count) {
				frappe.dom.unfreeze();
			}
			frm.refresh();
		}
	);
};

let make_bank_entry = function (frm) {
	var doc = frm.doc;
	if (doc.payment_account) {
		return frappe.call({
			method: "run_doc_method",
			args: {
				method: "make_bank_entry",
				dt: "Payroll Entry",
				dn: frm.doc.name,
			},
			callback: function () {
				frappe.set_route("List", "Journal Entry", {
					"Journal Entry Account.reference_name": frm.doc.name,
				});
			},
			freeze: true,
			freeze_message: __("Creating Payment Entries......"),
		});
	} else {
		frappe.msgprint(__("Payment Account is mandatory"));
		frm.scroll_to_field("payment_account");
	}
};

let render_employee_attendance = function (frm, data) {
	frm.fields_dict.attendance_detail_html.html(
		frappe.render_template("employees_with_unmarked_attendance", {
			data: data,
		})
	);
};
