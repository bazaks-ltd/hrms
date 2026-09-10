<template>
	<BaseLayout :pageTitle="__('Salary Slips')">
		<template #body>
			<div class="flex flex-col items-center my-7 p-4">
				<div class="flex flex-col w-full bg-white rounded py-5 px-3.5 gap-5">
					<div v-if="lastSalarySlip" class="flex flex-col w-full gap-1.5">
						<span class="text-gray-600 text-sm font-medium leading-5">
							{{ __("Year To Date") }}
						</span>
						<span class="text-gray-800 text-xl font-bold leading-6">
							{{ formatCurrency(lastSalarySlip.year_to_date, lastSalarySlip.currency) }}
						</span>
					</div>

					<Autocomplete
						v-if="periodOptions.length"
						:label="__('Payroll Period')"
						class="w-full"
						:placeholder="__('Select Payroll Period')"
						v-model="selectedPeriod"
						:options="periodOptions"
					/>
				</div>

				<div class="flex flex-col items-center mt-5 mb-7 w-full">
					<div
						v-if="visibleSlips.length"
						class="flex flex-col bg-white rounded mt-5 overflow-auto w-full"
					>
						<router-link
							class="p-3.5 items-center justify-between border-b cursor-pointer"
							v-for="link in visibleSlips"
							:key="link.name"
							:to="{
								name: 'SalarySlipDetailView',
								params: { id: link.name },
							}"
						>
							<SalarySlipItem :doc="link" />
						</router-link>
					</div>
					<EmptyState message="No salary slips found" v-else />
				</div>
			</div>
		</template>
	</BaseLayout>
</template>

<script setup>
import { inject, ref, computed, onMounted, onBeforeUnmount } from "vue"
import { Autocomplete, createResource } from "frappe-ui"

import BaseLayout from "@/components/BaseLayout.vue"
import EmptyState from "@/components/EmptyState.vue"
import SalarySlipItem from "@/components/SalarySlipItem.vue"

import { formatCurrency } from "@/utils/formatters"

const selectedPeriod = ref({})

const employee = inject("$employee")
const dayjs = inject("$dayjs")
const socket = inject("$socket")

const salarySlipData = createResource({
	url: "pcare.overrides.salary_slip_permission.get_employee_salary_slips",
	auto: true,
	cache: "hrms:employee_salary_slips",
})

const periodOptions = computed(() => {
	return (salarySlipData.data?.periods || []).map((period) => ({
		label: getPeriodLabel(period),
		value: period.name,
		start_date: period.start_date,
		end_date: period.end_date,
	}))
})

const visibleSlips = computed(() => {
	const slips = salarySlipData.data?.slips || []
	const period = periodOptions.value.find((option) => option.value === selectedPeriod.value?.value)
	if (!period?.start_date || !period?.end_date) {
		return slips
	}
	return slips.filter((slip) => slip.start_date >= period.start_date && slip.start_date <= period.end_date)
})

const lastSalarySlip = computed(() => visibleSlips.value?.[0])

function getPeriodLabel(period) {
	return `${dayjs(period?.start_date).format("MMM YYYY")} - ${dayjs(period?.end_date).format(
		"MMM YYYY"
	)}`
}

onMounted(() => {
	socket.on("hrms:update_salary_slips", (data) => {
		if (data.employee === employee.data.name) {
			salarySlipData.reload()
		}
	})
})

onBeforeUnmount(() => {
	socket.off("hrms:update_salary_slips")
})
</script>
