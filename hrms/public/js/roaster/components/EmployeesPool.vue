<script setup>
import { ref, watch, defineProps } from 'vue'

const props = defineProps(['filter', 'selected'])
const emits = defineEmits(['update:selected'])
const fetchedList = ref([])
const lists = ref([])
const selectedList = ref([])


const fetchEmployees = () => {
	const filters = [];
	if (props.filter.company) {
		filters.push(["company", "=", props.filter.company])
	}
	if (props.filter.department) {
		filters.push(["department", "=", props.filter.department])
	}
	if (props.filter.designation) {
		filters.push(["designation", "=", props.filter.designation])
	}

	if (filters.length === 0) {
		lists.value = []
		return;
	}

	frappe.db.get_list("Employee", {
		limit: 100,
		fields: ["*"],
		filters: filters
	}).then(res => {
		lists.value = res
	})
}

watch(() => props.filter, () => {
	fetchEmployees()
}, {
	// immediate: true,
	deep: true
})
watch(selectedList, () => {
	emits('update:selected', selectedList.value)
}, {
	deep: true
})
const onEmployeeSelected = (i) => {
	const emp = lists.value.splice(i, 1)
	lists.value = [...lists.value];
	emp[0].index = i;
	selectedList.value.push(emp[0])
}

</script>
<template>
	<div class="row form-section card-section">
		<div class="section-head">
			Employees
		</div>
		<div class="col-sm-12 form-section-description">
			Click on the employees to add to the roaster
		</div>
		<div class="section-body">
			<div class="d-flex flex-wrap p-2">
				<button v-for="(emp, i) in lists" class="btn btn-primary m-1" type="button"
					@click="onEmployeeSelected(i)">
					{{ emp.employee_name }}
				</button>
			</div>


		</div>
	</div>
</template>
