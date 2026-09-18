// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee Health Insurance", {
	refresh: function (frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Create New Cover"), function () {
				frappe.model.open_mapped_doc({
					method:
						"hrms.hr.doctype.employee_health_insurance.employee_health_insurance.make_new_cover",
					frm: frm,
				});
			});
			load_cover_history(frm);
		}
	},
});

function load_cover_history(frm) {
	if (!frm.doc.employee || !frm.fields_dict.cover_history_html) {
		return;
	}

	frappe.call({
		method: "hrms.hr.doctype.employee_health_insurance.employee_health_insurance.get_cover_history",
		args: {
			employee: frm.doc.employee,
			exclude: frm.doc.name,
		},
		callback: function (r) {
			frm.fields_dict.cover_history_html.$wrapper.html(cover_history_table(r.message || []));
		},
	});
}

function cover_history_table(rows) {
	if (!rows.length) {
		return `<p class="text-muted">${__("No other covers for this employee.")}</p>`;
	}

	const body = rows
		.map((row) => {
			return `<tr>
				<td><a href="/app/employee-health-insurance/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(
					row.name
				)}</a></td>
				<td>${frappe.datetime.str_to_user(row.enrolment_date) || ""}</td>
				<td>${row.valid_upto ? frappe.datetime.str_to_user(row.valid_upto) : __("Open")}</td>
				<td>${cint(row.is_active) ? __("Active") : __("Inactive")}</td>
				<td class="text-right">${format_currency(row.inpatient_cover)}</td>
				<td class="text-right">${format_currency(row.outpatient_cover)}</td>
				<td class="text-right">${format_currency(row.insurance_catastrophe_cover)}</td>
				<td class="text-right">${format_currency(row.self_deduction)}</td>
				<td class="text-right">${format_currency(row.employer_contribution)}</td>
			</tr>`;
		})
		.join("");

	return `<div class="table-responsive">
		<table class="table table-bordered table-condensed">
			<thead>
				<tr>
					<th>${__("Cover")}</th>
					<th>${__("Enrolment Date")}</th>
					<th>${__("Valid Upto")}</th>
					<th>${__("Status")}</th>
					<th>${__("Inpatient Cover")}</th>
					<th>${__("Outpatient Cover")}</th>
					<th>${__("Catastrophe Cover")}</th>
					<th>${__("Self Deduction")}</th>
					<th>${__("Employer Contribution")}</th>
				</tr>
			</thead>
			<tbody>${body}</tbody>
		</table>
	</div>`;
}

function cint(value) {
	return value ? 1 : 0;
}
