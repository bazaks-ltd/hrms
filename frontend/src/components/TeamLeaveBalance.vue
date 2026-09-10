<template>
	<div v-if="hasTeamBalances" class="flex flex-col w-full mt-7">
		<div class="px-4 text-lg text-gray-800 font-bold">
			{{ __("Team Leave Balance") }}
		</div>

		<div
			v-for="team in visibleTeams"
			:key="team.name"
			class="mt-3 px-4 w-full"
		>
			<div
				v-if="showTeamNames"
				class="text-sm font-semibold text-gray-600 mb-2"
			>
				{{ team.team_name }}
			</div>
			<div class="bg-white rounded-lg drop-shadow-md overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="border-b text-left text-gray-600">
							<th class="p-3 font-semibold whitespace-nowrap">
								{{ __("Employee") }}
							</th>
							<th
								v-for="leaveType in team.leave_types"
								:key="leaveType"
								class="p-3 font-semibold whitespace-nowrap"
							>
								{{ __(leaveType, null, "Leave Type") }}
							</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="member in team.members"
							:key="member.employee"
							class="border-b last:border-0"
						>
							<td class="p-3 text-gray-800 whitespace-nowrap">
								{{ member.employee_name }}
							</td>
							<td
								v-for="leaveType in team.leave_types"
								:key="leaveType"
								class="p-3 text-gray-800 whitespace-nowrap"
							>
								{{ formatBalance(member.balances?.[leaveType]) }}
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue"

import { hodTeamLeaveBalances } from "@/data/leaves"

const visibleTeams = computed(() => {
	return (hodTeamLeaveBalances.data || []).filter(
		(team) => (team.members || []).length
	)
})

const hasTeamBalances = computed(() => visibleTeams.value.length > 0)

const showTeamNames = computed(() => visibleTeams.value.length > 1)

const formatBalance = (allocation) => {
	const balance = allocation?.balance_leaves ?? 0
	const allocated = allocation?.allocated_leaves ?? 0
	return `${balance} / ${allocated}`
}
</script>
