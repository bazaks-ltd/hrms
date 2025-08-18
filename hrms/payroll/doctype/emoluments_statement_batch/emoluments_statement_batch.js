// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Emoluments Statement Batch", {
	refresh(frm) {
        if (frm.doc.docstatus === 0 && !frm.is_new()) {
            frm.page.clear_primary_action();
            frm.add_custom_button(__("Get Employees"), function () {
                frm.events.get_employee_details(frm);
            }).toggleClass("btn-primary", !(frm.doc.employees || []).length);
        }

        frm.add_custom_button(__("Print"), function () {
            frm.events.print_doc(frm);
        })

		if (
			(frm.doc.employees || []).length &&
			!frappe.model.has_workflow(frm.doctype) &&
			frm.doc.docstatus != 2
		) {
			console.log("Adding Create Salary Slips button");
			if (frm.doc.docstatus == 0 && !frm.is_new()) {
				frm.page.clear_primary_action();
				frm.page.set_primary_action(__("Create Emolument Statements"), () => {
					console.log("Creating Emolument Statements");
					frm.save("Submit").then(() => {
						console.log("Document status:", frm.doc.docstatus);
						frm.page.clear_primary_action();
						frm.refresh();
					});
				});
			} else if (frm.doc.docstatus == 1 && frm.doc.status == "Failed") {
				frm.add_custom_button(__("Create Emolument Statements"), function () {
					frm.events.create_emolument_statements(frm);
				}).addClass("btn-primary");
			}
		}
	},
	create_emolument_statements: function (frm) {
		console.log("calling the batch")
		frm.call({
			doc: frm.doc,
			method: "run_doc_method",
			args: {
				method: "create_emolument_statements",
				dt: "Emoluments Statement Batch",
				dn: frm.doc.name,
			},
		});
	},
    print_doc: function (frm) {
        console.log("printing")
        return frappe
			.call({
				doc: frm.doc,
				method: "print_data"
		})
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

				frm.scroll_to_field("employees");
			});
	},
});
