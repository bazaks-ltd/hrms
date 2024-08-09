// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// import TestVue from "./test.vue";

frappe.ui.form.on("Provisional Plan", {
	onload(frm) {
		frm.set_value("start_date", frappe.datetime.get_today());

		const $roaster_vue_wrapper = frm.get_field("roaster_vue").$wrapper;
		$roaster_vue_wrapper.empty();
		hrms.renderTest($roaster_vue_wrapper.get(0), {});

		// frm.vm = vm;
	},
});
