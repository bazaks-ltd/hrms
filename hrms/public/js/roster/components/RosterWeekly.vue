<script setup>
import { ref, defineEmits, defineProps, watch, computed } from "vue";
import DoctypeMultiSelect from "./core/DoctypeMultiSelect.vue";
import DoctypeAutoComplete from "./core/DoctypeAutoComplete.vue";
const shiftDepartment = ref(null);
const shifts = ref([]);
const shiftsMap = ref({});
const update = ref(0);
const department = "Sector 1";
const daysOfTheWeek = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const months = [
	"Jan",
	"Feb",
	"Mar",
	"Apr",
	"May",
	"Jun",
	"Jul",
	"Aug",
	"Sep",
	"Oct",
	"Nov",
	"Dec",
];
const props = defineProps(["startDate", "shift", "employees"]);

const currentDate = computed(() => new Date(props.startDate.getTime()));
const prevSunday = computed(
	() =>
		new Date(
			currentDate.value.setDate(currentDate.value.getDate() - currentDate.value.getDay())
		)
);
const currentYear = computed(() => currentDate.value.getFullYear());

const dayIndex = null;

const emits = defineEmits(["update:shift", "update:startDate", "update:employees", "depchange"]);

const activeWorking = (index, shift) => {
	const res = {};
	let total = 0;
	for (const element of shift) {
		const s = element;
		if (s[index] !== "R") {
			total += 1;
			if (res[s[index]]) {
				res[s[index]] += 1;
			} else {
				res[s[index]] = 1;
			}
		}
	}
	res.total = total;
	return res;
};

const getDateBaseOnSunday = (index) => {
	const d = new Date(prevSunday.value.getTime());
	return new Date(d.setDate(d.getDate() + index));
};

const hoursWorked = (arr) => {
	let result = 0;
	for (let a of arr) {
		if (shiftsMap.value && shiftsMap.value[a]) {
			result += shiftsMap.value[a].effective_hours;
		}
	}
	return result;
};

const input = (event, row, col) => {
	event.target.innerText = event.target.innerText.toUpperCase();
	const c = [...props.shift];
	c[row][col] = event.target.innerText;
	emits("update:shift", c);
};

const validate = (event) => {
	let valids = [];
	if (shifts.value) valids = shifts.value.map((s) => s.shift_suffix);
	valids.push("R");

	valids = [...valids, ...valids.map((v) => v.toLowerCase())];
	if (valids.indexOf(event.key) === -1) {
		event.preventDefault();
	} else {
		event.target.innerText = "";
	}
};

const onPaste = (evt) => {
	evt.preventDefault();
	const text = evt.clipboardData.getData("text/plain");
	const rows = text.split("\n");
	const nShift = [];
	for (const element of rows) {
		const cols = element.split("\t");
		const f = cols.filter((c) => ["r", "d", "n"].indexOf(c.toLowerCase()) !== -1);
		if (f.length !== 7) {
			return;
		}

		nShift.push(cols);
	}
	emits("update:shift", nShift);
	numberOfEmployees.value = nShift.length;
};

const numberOfEmployees = ref(0);
const onNumberOfEmployeesChange = (value) => {
	numberOfEmployees.value = value;

	const shift = [...props.shift];
	if (value > shift.length) {
		const diff = value - shift.length;
		for (let i = 0; i < diff; i++) {
			shift.push(Array(7).fill("R"));
		}
	} else {
		shift.splice(value, shift.length - value);
	}
	emits("update:shift", shift);
};

watch(
	() => props.employees,
	() => {
		if (numberOfEmployees.value === 0) {
			onNumberOfEmployeesChange(props.employees.length);
		}
	}
);

const selectedDragIndex = ref(-1);
const onDragOverIndex = (index) => {
	selectedDragIndex.value = index;
};

const onDrop = (event) => {
	// event.preventDefault();
	// const data = event.dataTransfer.getData("text");
	// const shift = [...props.shift]
	// shift[data] = Array(7).fill('R')
	// emits('update:shift', shift)

	const data = event.dataTransfer.getData("emp");
	const emp = JSON.parse(data);

	const employees = [...props.employees];
	employees[selectedDragIndex.value] = emp;
	emits("update:employees", employees);

	selectedDragIndex.value = -1;
};

const onEmployeeAdded = (emp) => {
	if (props.employees.findIndex((a) => a.name === emp.name) === -1) {
		// onNumberOfEmployeesChange(props.employees.length + 1);
		emits("update:employees", [...props.employees, emp]);
	}
};
const ratio = ref(2);

function generateRoster(numEmployees) {
	const dayNightRatio = ratio.value;

	const numDays = 7;
	const sundays = [6]; // Sunday is the 7th day (index 6)
	const totalShifts = numDays - 2; // Total shifts, leaving room for rest days

	const totalNightShifts = Math.floor(totalShifts / (dayNightRatio + 1));
	const totalDayShifts = totalShifts - totalNightShifts;

	// Initialize an empty roster
	const roster = Array.from({ length: numEmployees }, () => Array(numDays).fill("D"));

	for (let i = 0; i < numEmployees; i++) {
		let row = Array(numDays).fill("D"); // Start with all day shifts

		// Add night shifts based on the ratio
		let nightShifts = 0;
		while (nightShifts < totalNightShifts) {
			const nightShiftIndex = Math.floor(Math.random() * numDays);
			if (row[nightShiftIndex] === "D" && nightShiftIndex !== sundays[0]) {
				row[nightShiftIndex] = "N";
				nightShifts++;
			}
		}

		// Add rest days
		let restDays = 0;
		while (restDays < 2) {
			// Ensure at least two rest days
			const restDayIndex = Math.floor(Math.random() * numDays);
			if (row[restDayIndex] === "D" || row[restDayIndex] === "N") {
				row[restDayIndex] = "R";
				restDays++;
			}
		}

		// Ensure Sunday has a rest day for some employees, but not all
		if (i % 2 === 0) {
			row[sundays[0]] = "R";
		}

		roster[i] = row;
	}

	emits("update:shift", roster);
}

const onRemoveEmployee = (i) => {
	console.log(i);
	const employees = [...props.employees];
	console.log(employees[i]);
	employees.splice(i, 1);
	emits("update:employees", employees);
};

watch(shiftDepartment, () => {
	shifts.value = [];
	emits("depchange", shiftDepartment.value);
	//fetch shifts
	frappe.db
		.get_list("Shift Type", {
			filters: { department: shiftDepartment.value },
			fields: ["*"],
			limit: 0,
		})
		.then((res) => {
			shifts.value = res;
			shiftsMap.value = res.reduce((acc, shift) => {
				acc[shift.shift_suffix] = shift;
				return acc;
			}, {});
		});
});
</script>
<template>
	<div class="row form-section card-section">
		<div class="section-head">Provisional Roster</div>
		<div class="section-body">
			<div class="">
				<DoctypeMultiSelect
					class="col-lg"
					title="Select Employee"
					doctype="Employee"
					field="employee_name"
					@add="onEmployeeAdded"
				/>
				<DoctypeAutoComplete
					class="col-lg"
					title="Department Shift"
					doctype="Department"
					v-model="shiftDepartment"
				/>
				<div class="shifts mb-4">
					<div v-for="shift in shifts" class="shift flex">
						<div class="font-bold pl-2">{{ shift.shift_suffix }}</div>
						<div class="px-2">{{ shift.start_time }} - {{ shift.end_time }}</div>
					</div>
				</div>
			</div>
		</div>
		<div class="section-body">
			<div class="form-column col-sm-2">
				<form>
					<div class="frappe-control input-max-width">
						<div class="form-group">
							<label>Paste Bin</label>
							<input type="text" class="form-control" @paste="onPaste" />
						</div>
					</div>
				</form>
			</div>
			<div class="form-column col-sm-4">
				<form>
					<div class="frappe-control input-max-width">
						<div class="form-group">
							<label>Number of Employees</label>
							<input
								type="number"
								class="form-control"
								:value="numberOfEmployees"
								@input="(event) => onNumberOfEmployeesChange(event.target.value)"
							/>
						</div>
					</div>
				</form>
			</div>
			<div class="form-column col-sm-4">
				<div class="frappe-control input-max-width">
					<div class="form-group">
						<label>Ratio</label>
						<input type="number" class="form-control" v-model="ratio" />
						<button class="btn btn-primary" @click="generateRoster(numberOfEmployees)">
							Random
						</button>
					</div>
				</div>
			</div>
		</div>

		<div v-if="props.shift.length > 0" class="section-body">
			<div class="flex mr-auto ml-auto">
				<div>
					<div class="">
						<div class="overflow-hidden">
							<div class="container">
								<div class="">
									<p class="font-bold my-2 text-center">{{ currentYear }}</p>
									<!-- <p>{{ startDate.getDay() }} {{ startDate.getDate() }}</p> -->
								</div>

								<table class="min-w-full divide-y divide-gray-200">
									<thead>
										<tr>
											<th
												scope="col"
												class="text-center p-4 text-xs font-medium text-gray-500 uppercase"
											></th>
											<th
												scope="col"
												v-for="(d, i) in daysOfTheWeek"
												class="text-center border text-xs p-4 font-medium text-gray-500 uppercase whitespace-nowrap"
												:class="{
													'bg-blue-100': i === dayIndex - 1,
												}"
											>
												{{ getDateBaseOnSunday(i + 1).getDate() }}
												{{ months[getDateBaseOnSunday(i + 1).getMonth()] }}
											</th>
											<th
												scope="col"
												class="text-center border text-xs font-medium text-gray-500 p-2"
											></th>
											<th
												scope="col"
												class="text-end text-xs font-medium text-gray-500 uppercase"
											></th>
										</tr>
										<tr>
											<th
												scope="col"
												class="text-center p-4 text-xs font-medium text-gray-500 uppercase"
											>
												No
											</th>
											<th
												scope="col"
												v-for="(d, i) in daysOfTheWeek"
												class="text-center border text-xs p-4 font-medium text-gray-500 uppercase whitespace-nowrap"
												:class="{
													'bg-blue-100': i === dayIndex - 1,
												}"
											>
												{{ d }}
											</th>
											<th
												scope="col"
												class="text-center border text-xs font-medium text-gray-500 p-2"
											>
												Weekly
												<br />
												Hrs
											</th>
											<th scope="col" class="text-center border uppercase">
												Employee
											</th>
										</tr>
									</thead>
									<tbody class="divide-y divide-gray-200">
										<tr v-for="(shift, i) in shift" class="h-5">
											<td
												class="text-center border whitespace-nowrap text-sm font-medium text-gray-800"
											>
												{{ i + 1 }}
											</td>
											<td
												v-for="(s, si) in shift"
												class="border text-center whitespace-nowrap text-sm text-gray-800 p-2"
												:class="{
													'bg-red-100': s === 'R',
													'bg-green-100':
														s === 'D' && si !== dayIndex - 1,
													'bg-green-300':
														s === 'N' && si !== dayIndex - 1,
													'bg-blue-100': si + 1 === dayIndex,
												}"
												contenteditable="true"
												@keypress="validate"
												@paste.prevent=""
												@input="(event) => input(event, i, si)"
											>
												{{ s }}
											</td>
											<td
												class="whitespace-nowrap text-center text-gray-400 text-sm font-medium border"
											>
												{{ hoursWorked(shift) }}
											</td>
											<td class="border">
												<!-- <button v-if="employees[i]" type="button" class="btn btn-primary">{{
													employees[i].employee_name }}</button> -->
												<button
													type="button"
													class="btn"
													:class="{
														'btn-info': selectedDragIndex === i,
														'btn-primary': selectedDragIndex !== i,
													}"
													@click="employees[i] && onRemoveEmployee(i)"
													@drop.prevent="onDrop"
													@dragenter.prevent
													@dragover.prevent="onDragOverIndex(i)"
												>
													{{
														employees[i]
															? employees[i].employee_name
															: "Assign Employee"
													}}
												</button>
											</td>
										</tr>
										<tr class="bg-orange-100">
											<td
												class="text-center border whitespace-nowrap text-sm font-medium text-gray-800"
											></td>
											<td
												v-for="(_, i) in 7"
												class="border text-center whitespace-nowrap text-sm text-gray-800 p-2"
												:class="{
													'bg-blue-100': i === dayIndex - 1,
												}"
											>
												<div>
													<div v-for="(v, k) in activeWorking(i, shift)">
														{{ v }} {{ k }}
													</div>
												</div>
											</td>

											<td
												class="whitespace-nowrap text-end text-sm font-medium"
											></td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style>
.bg-red-100 {
	background-color: #fee2e2;
}

.bg-blue-100 {
	background-color: #dbeafe;
}

.bg-green-100 {
	background-color: #f0fff4;
}

.bg-green-300 {
	background-color: #c6f6d5;
}
</style>
