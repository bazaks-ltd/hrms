<script setup lang="ts">
import { ref, reactive, defineEmits, defineProps, onMounted } from 'vue'
import { watchDebounced } from '@vueuse/core'


const fields = [
	{
		name: 'title',
		label: 'Title',
		type: 'text'
	}, {
		name: 'start_date',
		label: 'Start Date',
		type: 'date'
	},
	// {
	// 	name: 'end_date',
	// 	label: 'End Date',
	// 	type: 'date'
	// }
]

const props = defineProps(['startDate', 'title'])
const provisionalPlan = reactive({
	title: null,
	start_date: null,
	end_date: ''
})

onMounted(() => {
	provisionalPlan.title = props.title
	provisionalPlan.start_date = new Date(props.startDate).toISOString().split('T')[0]
})

const emits = defineEmits(['change'])

watchDebounced(
	provisionalPlan,
	() => {
		emits('change', provisionalPlan)
	},
	{ debounce: 500 },
)

</script>
<template>
	<div class="row form-section card-section">
		<div class="section-head">
			Details
		</div>
		<div class="section-body">
			<div v-for="field in fields" class="form-column col-sm-4">
				<form>
					<div class="frappe-control input-max-width">
						<div class="form-group">
							<label :for="field.name">{{ field.label }}</label>
							<input :type="field.type" class="form-control" :id="field.name"
								v-model="provisionalPlan[field.name]">
						</div>
					</div>

				</form>
			</div>

		</div>
	</div>
</template>
