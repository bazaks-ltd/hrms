<script setup lang="ts">
import { ref, computed } from 'vue';
const route = frappe.get_route().filter(r => r !== '').slice(1);
import Main from './Main.vue';
import List from './List.vue';
import Real from './Real.vue';

</script>
<template>
	<div id="app">
		<List v-if="route.length === 0" />
		<Main v-else-if="route.join().includes('new')" />
		<Real v-else />
	</div>
</template>
