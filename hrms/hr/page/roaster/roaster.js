frappe.pages["roaster"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Provisional Plan"),
		single_column: true,
	});
};

frappe.pages["roaster"].on_page_show = function (wrapper) {
	load_desk_page(wrapper);
};

function load_desk_page(wrapper) {
	let $parent = $(wrapper).find(".layout-main-section");
	$parent.empty();

	frappe.require("roaster.bundle.js").then(() => {
		frappe.roaster = new frappe.ui.Roaster({
			wrapper: $parent,
			page: wrapper.page,
		});
	});
}
