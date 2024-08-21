import { createApp } from "vue";
import App from "./App.vue";

class Roster {
	constructor({ page, wrapper }) {
		this.$wrapper = $(wrapper);
		this.page = page;

		this.init();
	}

	init() {
		this.setup_page_actions();
		this.setup_app();
	}

	setup_page_actions() {
		// setup page actions
		// 	this.primary_btn = this.page.set_primary_action(__("Print Message"), () =>
		//   frappe.msgprint("Hello My Page!")
		// 	);
	}

	setup_app() {
		if (this.$wrapper.get(0).__vue__app !== undefined) {
			console.log("Vue app already mounted");
		} else {
			// create a vue instance
			let app = createApp(App);
			// mount the app
			this.$roster = app.mount(this.$wrapper.get(0));
		}
	}
}

frappe.provide("frappe.ui");
frappe.ui.Roster = Roster;
export default Roster;
