<script setup lang="ts">
import { ref, computed, defineProps, watch, onMounted } from "vue";
import moment from "moment";

const props = defineProps([
  "shifts",
  "employees",
  "startDate",
  "shiftDeparment",
]);
const startDateIndex = computed(() => {
  const s = new Date(props.startDate.getTime());
  const d = new Date(s.setDate(s.getDate() - s.getDay()));
  return new Date(d.setDate(d.getDate() + 1)).getDate();
});
const startOfMonth = computed(() => {
  return new Date(props.startDate.getFullYear(), props.startDate.getMonth(), 1);
});
const numberOfDaysInMonth = computed(() => {
  return new Date(
    props.startDate.getFullYear(),
    props.startDate.getMonth() + 1,
    0
  ).getDate();
});

const numberOfEmployees = computed(() => {
  return props.shifts.length;
});

const uShifts = computed(() => {
  return props.shifts.flat(1);
});

const getShift = (i, ei) => {
  const value = (i - (startDateIndex.value - ei * 7)) % uShifts.value.length;
  if (value >= 0) {
    return uShifts.value[value];
  } else {
    return uShifts.value[uShifts.value.length + value];
  }
};

const computedShifts = computed(() => {
  return Array(numberOfEmployees.value)
    .fill(0)
    .map((_, i) => {
      return Array(numberOfDaysInMonth.value)
        .fill(0)
        .map((_, j) => {
          return getShift(j + 1, i);
        });
    });
});

const hoursWorked = (arr) => {
  let result = 0;
  for (let a of arr) {
    if (shiftsMap.value && shiftsMap.value[a]) {
      result += shiftsMap.value[a].effective_hours;
    }
  }
  return result;
};

const computedMontlyHours = computed(() => {
  return computedShifts.value.map((shift) => {
    return hoursWorked(shift);
  });
});

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

const depShifts = ref([]);
const shiftsMap = ref({});

onMounted(() => {
  fetchShifts();
});
watch(
  () => props.shiftDeparment,
  () => {
    fetchShifts();
  }
);

const fetchShifts = () => {
  depShifts.value = [];
  console.log("fetching .....");
  //fetch shifts
  frappe.db
    .get_list("Shift Type", {
      filters: { department: props.shiftDeparment },
      fields: ["*"],
      limit: 0,
    })
    .then((res) => {
      depShifts.value = res;
      shiftsMap.value = res.reduce((acc, shift) => {
        acc[shift.shift_suffix] = shift;
        return acc;
      }, {});
    });
};
</script>
<template>
  <h2 class="mx-auto text-center py-4">
    {{ moment(startOfMonth).format("MMM YYYY") }}
  </h2>
  <div>{{ props.shiftDeparment }}</div>
  <div class="w-100 table-responsive">
    <table class="table table-bordered w-auto">
      <thead>
        <tr>
          <th scope="col" class="text-nowrap">Employee Name</th>
          <th scope="col" class="text-nowrap">Monthly hrs</th>
          <th
            v-for="i in numberOfDaysInMonth"
            scope="col"
            class="text-center text-sm"
            :class="{
              'bg-danger text-white': startDateIndex === i,
            }"
          >
            {{ i }}
          </th>
        </tr>
        <tr>
          <th scope="col" class="text-nowrap">Day</th>
          <th scope="col" class="text-nowrap"></th>
          <th
            v-for="i in numberOfDaysInMonth"
            scope="col"
            class="px-4"
            :class="{
              'bg-danger text-white': startDateIndex === i,
            }"
          >
            {{
              moment(startOfMonth)
                .add(i - 1, "d")
                .format("ddd")
            }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(e, ei) in numberOfEmployees">
          <th scope="row" class="text-nowrap">
            {{ props.employees[ei].employee_name }}
          </th>
          <td scope="row" class="text-center">{{ computedMontlyHours[ei] }}</td>
          <td
            v-for="i in numberOfDaysInMonth"
            class="text-center"
            :class="{
              'bg-red-100': computedShifts[ei][i - 1] === 'R',
              'bg-green-100': computedShifts[ei][i - 1] === 'D',
              'bg-green-300': computedShifts[ei][i - 1] === 'N',
            }"
          >
            {{ computedShifts[ei][i - 1] }}
          </td>
        </tr>
        <tr class="bg-orange-100">
          <td
            class="text-center border whitespace-nowrap text-sm font-medium text-gray-800"
          ></td>
          <td
            class="text-center border whitespace-nowrap text-sm font-medium text-gray-800"
          ></td>
          <td
            v-for="i in numberOfDaysInMonth"
            class="border text-center whitespace-nowrap text-sm text-gray-800 p-2"
          >
            <div>
              <div v-for="(v, k) in activeWorking(i - 1, computedShifts)">
                {{ v }} {{ k }}
              </div>
            </div>
          </td>

          <td class="whitespace-nowrap text-end text-sm font-medium"></td>
        </tr>
      </tbody>
    </table>
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
