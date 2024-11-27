<script setup lang="ts">
import { reactive, watch, defineEmits } from "vue";
import DoctypeAutoComplete from "./core/DoctypeAutoComplete.vue";
const values = reactive({
	company: undefined,
	department: undefined,
	designation: undefined,
});
const emits = defineEmits(["change"]);
watch(values, () => {
	emits("change", values);
});
</script>

<template>
	<div class="row form-section card-section">
		<div class="section-head">Filters</div>
		<div class="col-sm-12 form-section-description">Set filters to fetch employees</div>
		<div class="section-body">
			<DoctypeAutoComplete
				class="col-lg"
				title="Company"
				doctype="Company"
				v-model="values.company"
			/>
			<DoctypeAutoComplete
				class="col-lg"
				title="Department"
				doctype="Department"
				v-model="values.department"
			/>
			<DoctypeAutoComplete
				class="col-lg"
				title="Designation"
				doctype="Designation"
				v-model="values.designation"
			/>
		</div>
	</div>
</template>
