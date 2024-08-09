<script setup>
import { ref, onMounted } from "vue";
import ProvisionalPlan from "./components/ProvisionalPlan.vue";
import EmployeesFilter from "./components/EmployeesFilter.vue";
import EmployeesPool from "./components/EmployeesPool.vue";
import RoasterWeekly from "./components/RoasterWeekly.vue";
const R = 'R' //rest day
const D = 'D' //jour
const N = 'N' //nuit

const shift = ref([
	[R, D, D, D, D, R, R],
	[D, D, D, D, R, D, D],
	[D, R, D, D, D, R, D],
	[D, D, R, D, D, D, R],
	[D, D, D, R, D, D, D],
	[D, R, D, D, D, R, D],
	[D, D, R, D, D, D, R],
	[R, D, D, R, D, D, D],
	[D, D, R, D, R, D, D],
	[D, R, D, D, D, R, R],
	[D, D, D, R, D, D, D],
	[R, D, D, R, R, D, D],

	[R, R, N, N, N, R, R],
	[N, N, R, R, R, N, N],
	[R, R, N, N, N, R, R],
	[N, N, R, R, R, N, N],
	[R, R, N, N, N, R, R],
	[N, N, R, R, R, N, N],
	[R, R, N, N, N, R, R],
	[N, N, R, R, R, N, N],
])

const startDate = ref(new Date("2024-10-01"))

const onProvionalPlanChange = (value) => {
	console.log(value);
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

onMounted(() => {

})
</script>
<template>
	<div>
		<div class="form-page">
			<ProvisionalPlan @change="onProvionalPlanChange" />
			<EmployeesFilter @change="onEmployeeFilterChange" />
			<EmployeesPool :filter="employeesFilter" v-model:selected="employees" />
			<RoasterWeekly v-model:shift="shift" :start-date="startDate" :employees="employees" />
			<div style="height: 100px;"></div>
		</div>
	</div>
</template>
