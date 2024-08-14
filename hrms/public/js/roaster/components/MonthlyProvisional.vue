<script setup lang="ts">
import { ref, computed, defineProps } from 'vue'
import moment from 'moment'

const startDate = new Date('2024-08-12')
const startOfMonth = ref(new Date(startDate.getFullYear(), startDate.getMonth(), 1))
const numberOfDaysInMonth = ref(new Date(startDate.getFullYear(), startDate.getMonth() + 1, 0).getDate())



const props = defineProps(['shifts', 'employees'])


const numberOfEmployees = computed(() => {
    return props.shifts.length
})

const uShifts = computed(() => {
    return props.shifts.flat(1)
})



const getShift = (i, ei) => {
    const value = (i - (startDateIndex - (ei * 7))) % uShifts.value.length
    if (value >= 0) {
        return uShifts.value[value]
    } else {
        return uShifts.value[uShifts.value.length + value]
    }


}

const computedShifts = computed(() => {
    return Array(numberOfEmployees.value).fill(0).map((_, i) => {
        return Array(numberOfDaysInMonth.value).fill(0).map((_, j) => {
            return getShift(j + 1, i)
        })
    })
})

const hoursWorked = (arr) => {

    let result = 0;
    for (let a of arr) {
        switch (a) {
            case "D":
                result += 9;
                break;
            case "N":
                result += 14;
                break;
            default:
                break;
        }
    }
    return result;
}

const computedMontlyHours = computed(() => {
    return computedShifts.value.map((shift) => {
        return hoursWorked(shift)
    })
})
const startDateIndex = 12
</script>
<template>
    <h2 class="mx-auto text-center py-4">{{ moment(startOfMonth).format("MMM YYYY") }}</h2>
    <div class="w-100 table-responsive">

        <table class="table table-bordered w-auto">
            <thead>
                <tr>
                    <th scope="col" class="text-nowrap">Employee Name </th>
                    <th scope="col" class="text-nowrap">Monthly hrs</th>
                    <th v-for="i in numberOfDaysInMonth" scope="col" class="text-center text-sm" :class="{
                        'bg-danger text-white': startDateIndex === i
                    }">{{ i }}</th>
                </tr>
                <tr>
                    <th scope="col" class="text-nowrap">Day </th>
                    <th scope="col" class="text-nowrap"></th>
                    <th v-for="i in numberOfDaysInMonth" scope="col" class="px-4" :class="{
                        'bg-danger text-white': startDateIndex === i
                    }">{{ moment(startOfMonth).add(i - 1, 'd').format("ddd") }}
                    </th>
                </tr>
            </thead>
            <tbody>
                <tr v-for="(e, ei) in numberOfEmployees">

                    <th scope="row" class="text-nowrap">{{ props.employees[ei].employee_name }}</th>
                    <td scope="row" class="text-center">{{ computedMontlyHours[ei] }}</td>
                    <td v-for="i in numberOfDaysInMonth" class="text-center" :class="{
                        'bg-red-100': computedShifts[ei][i - 1] === 'R',
                        'bg-green-100': computedShifts[ei][i - 1] === 'D',
                        'bg-green-300': computedShifts[ei][i - 1] === 'N'
                    }">{{ computedShifts[ei][i - 1] }}</td>
                </tr>

            </tbody>
        </table>

    </div>
</template>

<style>
.bg-red-100 {
    background-color: #FEE2E2;
}

.bg-blue-100 {
    background-color: #DBEAFE;
}

.bg-green-100 {
    background-color: #F0FFF4;
}

.bg-green-300 {
    background-color: #C6F6D5;
}
</style>