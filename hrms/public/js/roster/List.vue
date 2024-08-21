<script setup lang="ts">
import DataTable from "frappe-datatable";
import { onMounted, ref } from "vue";
const datatable = ref(null);
const lists = ref([]);

onMounted(() => {
	frappe.breadcrumbs.clear()
	frappe.breadcrumbs.add('HR')

	frappe.db.get_list("Provisional Plan", {
		limit: 0,
		fields: ["*"],
	}).then(res => {
		lists.value = res
	})



})

const onNewRoster = () => {
	frappe.set_route(['roster', 'new'])
}

const navigateTo = (id) => {
	frappe.set_route(['roster', id])
}
</script>
<template>

	<button @click="onNewRoster" class="btn btn-primary">new</button>
	<table class="table table-hover">
		<thead>
			<tr>
				<th scope="col">#</th>
				<th scope="col">Name</th>
				<th scope="col">Department</th>
				<th scope="col">Month</th>
				<th scope="col">Title</th>
				<!-- <th scope="col">Action</th> -->
			</tr>
		</thead>
		<tbody>
			<tr v-for="(l, i) in lists" @click="navigateTo(l.name)">
				<th scope="row">{{ i + i }}</th>
				<td>{{ l.name }}</td>
				<td>{{ l.department }}</td>
				<td>{{ l.month + " " + l.year }}</td>
				<td>{{ l.title }}</td>
				<!-- <td>
					<button class="btn btn-primary rounded-circle mr-2"> <i
							class="octicon octicon-pencil "></i></button>
					<button class="btn btn-danger rounded-circle"><i class="octicon octicon-trashcan "></i></button>
				</td> -->
			</tr>

		</tbody>
	</table>
</template>
