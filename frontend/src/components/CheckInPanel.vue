<template>
	<div class="flex flex-col bg-white rounded w-full py-6 px-4 border-none">
		<h2 class="text-lg font-bold text-gray-900">
			{{ __("Hey, {0} 👋", [employee?.data?.first_name]) }}
		</h2>
		<div class="font-medium text-sm text-gray-500 mt-1.5">
			{{ dayjs().format("ddd, D MMMM, YYYY") }}
		</div>
	</div>
</template>

<script setup>
import { inject } from "vue"

const employee = inject("$employee")
const dayjs = inject("$dayjs")
const __ = inject("$translate")
</script>
