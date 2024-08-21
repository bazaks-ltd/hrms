frappe.pages["roster"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Provisional Plan"),
		single_column: true,
	});
};

frappe.pages["roster"].on_page_show = function (wrapper) {
	load_desk_page(wrapper);
};

function load_desk_page(wrapper) {
	let $parent = $(wrapper).find(".layout-main-section");
	$parent.empty();

	frappe.require("roster.bundle.js").then(() => {
		frappe.roster = new frappe.ui.Roster({
			wrapper: $parent,
			page: wrapper.page,
		});
	});
}
