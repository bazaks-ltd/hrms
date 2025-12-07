// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Leave Refund", {
	onload: function (frm) {
		// Ignore cancellation of doctype on cancel all.
		frm.ignore_doctypes_on_cancel_all = ["Leave Ledger Entry"];
	},
	setup: function (frm) {
		frm.set_query("leave_type", function () {
			return {
				filters: {
					// Allow any leave type for refund
				},
			};
		});
		frm.set_query("salary_component", function () {
			return {
				filters: {
					type: "Earning",
				},
			};
		});
	},
	refresh: function (frm) {
		cur_frm.set_intro("");
		if (frm.doc.__islocal && !frappe.user_roles.includes("Employee")) {
			frm.set_intro(__("Fill the form and save it"));
		}

		// Add view ledger button if available
		if (typeof hrms !== "undefined" && hrms.leave_utils) {
			hrms.leave_utils.add_view_ledger_button(frm);
		}
	},
	employee: function (frm) {
		if (frm.doc.employee) {
			frappe.run_serially([
				() => frm.trigger("get_employee_currency"),
				() => frm.trigger("get_leave_details_for_refund"),
			]);
		}
	},
	leave_type: function (frm) {
		frm.trigger("get_leave_details_for_refund");
	},
	refund_date: function (frm) {
		frm.trigger("get_leave_details_for_refund");
	},
	refund_days: function (frm) {
		if (frm.doc.refund_days && frm.doc.employee && frm.doc.leave_type) {
			frm.trigger("get_leave_details_for_refund");
		}
	},
	get_leave_details_for_refund: function (frm) {
		frm.set_value("leave_balance", 0);

		if (frm.doc.docstatus === 0 && frm.doc.employee && frm.doc.leave_type) {
			return frappe.call({
				method: "get_leave_details_for_refund",
				doc: frm.doc,
				callback: function (r) {
					frm.refresh_fields();
				},
			});
		}
	},

	get_employee_currency: function (frm) {
		frappe.call({
			method: "hrms.payroll.doctype.salary_structure_assignment.salary_structure_assignment.get_employee_currency",
			args: {
				employee: frm.doc.employee,
			},
			callback: function (r) {
				if (r.message) {
					frm.set_value("currency", r.message);
					frm.refresh_fields();
				}
			},
		});
	},
});

