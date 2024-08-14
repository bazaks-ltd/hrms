<script setup>
import { ref, onMounted, computed } from "vue";
import ProvisionalPlan from "./components/ProvisionalPlan.vue";
import EmployeesFilter from "./components/EmployeesFilter.vue";
import EmployeesPool from "./components/EmployeesPool.vue";
import RoasterWeekly from "./components/RoasterWeekly.vue";
import MonthlyProvisional from "./components/MonthlyProvisional.vue";


const R = 'R' //rest day
const D = 'D' //jour
const N = 'N' //nuit

const shift = ref([])

const startDate = ref(new Date())

const onProvionalPlanChange = (value) => {
	startDate.value = new Date(value.start_date);
}

const employeesFilter = ref({
	company: undefined,
	department: undefined,
	designation: undefined
})
const onEmployeeFilterChange = (value) => {
	employeesFilter.value = value;
}

const title = ref("Provisional")
const employees = ref([])

const validateMonthlyView = computed(() => {

	if (shift.value.length === employees.value.length && shift.value.length > 0) {
		for (const emp of employees.value) {
			if (!emp || emp.length === 0) {
				return false
			}

		}
		return true
	}
	return false
})


</script>
<template>
	<div>
		<div class="form-page">
			<ProvisionalPlan @change="onProvionalPlanChange" />
			<EmployeesFilter @change="onEmployeeFilterChange" />
			<EmployeesPool :filter="employeesFilter" v-model:selected="employees" />
			<RoasterWeekly v-model:shift="shift" :start-date="startDate" v-model:employees="employees" />
			<MonthlyProvisional v-if="validateMonthlyView" :shifts="shift" :employees="employees" />
			<div style="height: 100px;"></div>
		</div>
	</div>
</template>
