<script setup>
import { ref, watch, defineProps } from 'vue'

const props = defineProps(['filter', 'selected'])
const emits = defineEmits(['update:selected'])
const lists = ref([])


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
		order_by: "name asc",
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

const onEmployeeSelected = (i) => {
	const emp = lists.value[i];
	if (props.selected.findIndex((a) => a.name === emp.name) === -1) {
		emits('update:selected', [...props.selected, emp])
	}
}



const onAssignAll = () => {
	emits('update:selected', [...lists.value])
}

const onDragStart = (e, emp) => {
	e.dataTransfer.setData('emp', JSON.stringify(emp));
}


</script>
<template>
	<div class="row form-section card-section">
		<div class="section-head">
			Employees
		</div>
		<div class="col-sm-12 form-section-description">
			Click on the employees to add to the roster
		</div>

		<div class="section-body">
			<div class="d-flex flex-column">
				<div class="d-flex flex-wrap p-2">

					<button v-for="(emp, i) in lists" class="btn btn-primary m-1 shadow-none" type="button"
						@click="onEmployeeSelected(i)"
						:disabled="props.selected.findIndex((a) => a.name === emp.name) !== -1"
						:draggable="props.selected.findIndex((a) => a.name === emp.name) === -1"
						@dragstart="e => onDragStart(e, emp)" @dragend="console.log(`cool`)">
						{{ emp.employee_name }}
					</button>
				</div>
				<div class="p-2">
					<button v-if="lists.length > 0" @click="onAssignAll" class="btn btn-secondary" type="button"> Assign
						All</button>
				</div>
			</div>


		</div>
	</div>
</template>
