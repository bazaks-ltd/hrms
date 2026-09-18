<template>
	<ion-page>
		<ion-content :fullscreen="true">
			<div class="flex flex-col h-full w-full">
				<div class="w-full h-full bg-white sm:w-96 flex flex-col">
					<header
						class="flex flex-row bg-white shadow-sm py-4 px-3 items-center sticky top-0 z-[1000]"
					>
						<Button
							variant="ghost"
							class="!pl-0 hover:bg-white"
							@click="router.back()"
						>
							<FeatherIcon name="chevron-left" class="h-5 w-5" />
						</Button>
						<div class="flex flex-row items-center gap-2 overflow-hidden grow">
							<h2
								class="text-xl font-semibold text-gray-900 whitespace-nowrap overflow-hidden text-ellipsis"
							>
								{{ __("Salary Slip") }}
							</h2>
							<Badge
								:label="props.id"
								class="whitespace-nowrap text-[8px]"
								variant="outline"
							/>
						</div>
					</header>

					<div class="bg-white grow overflow-y-auto">
						<div
							v-if="printPreview.loading"
							class="flex mt-8 items-center justify-center"
						>
							<LoadingIndicator class="w-8 h-8 text-gray-800" />
						</div>
						<ErrorMessage
							v-else-if="printPreview.error"
							:message="printPreview.error"
							class="m-4"
						/>
						<iframe
							v-else-if="printSrcdoc"
							:srcdoc="printSrcdoc"
							class="w-full border-0 bg-white"
							title="Salary Slip"
							@load="onPrintFrameLoad"
						></iframe>
					</div>

					<div
						class="px-4 pt-4 pb-4 standalone:pb-safe-bottom sm:w-96 bg-white sticky bottom-0 w-full drop-shadow-xl z-40 border-t rounded-t-lg"
					>
						<ErrorMessage :message="downloadError" class="mt-2" />
						<Button
							class="w-full rounded py-5 text-base disabled:bg-gray-700 disabled:text-white"
							@click="downloadPDF"
							variant="solid"
							:loading="loading"
						>
							{{ __("Download PDF") }}
						</Button>
					</div>
				</div>
			</div>
		</ion-content>
	</ion-page>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { useRouter } from "vue-router"
import { IonPage, IonContent } from "@ionic/vue"
import {
	Badge,
	createResource,
	ErrorMessage,
	FeatherIcon,
	LoadingIndicator,
} from "frappe-ui"

const props = defineProps({
	id: {
		type: String,
		required: true,
	},
})

const router = useRouter()
const downloadError = ref("")
const loading = ref(false)

const printPreview = createResource({
	url: "hrms.api.get_salary_slip_print",
	params: { name: props.id },
	auto: true,
})

watch(
	() => props.id,
	(name) => {
		if (!name) return
		printPreview.update({ params: { name } })
		printPreview.reload()
	}
)

const printSrcdoc = computed(() => {
	if (!printPreview.data?.html) return ""

	const style = printPreview.data.style || ""
	const html = printPreview.data.html
	const origin = window.location.origin

	return `<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<base href="${origin}/">
	<style>${style}</style>
	<style>
		html, body {
			margin: 0;
			padding: 0;
			background: #fff;
		}
		.print-format {
			margin: 0 !important;
			padding: 8px !important;
			box-shadow: none !important;
			min-height: auto !important;
		}
		.salary-details {
			display: block !important;
		}
		.col-100 {
			display: block !important;
			width: 100% !important;
			padding: 0 !important;
			margin-bottom: 12px;
		}
	</style>
</head>
<body>
	<div class="print-format">${html}</div>
</body>
</html>`
})

function onPrintFrameLoad(event) {
	const iframe = event.target
	const doc = iframe.contentDocument
	if (!doc?.body) return

	const resize = () => {
		iframe.style.height = `${doc.documentElement.scrollHeight}px`
	}

	resize()
	if (typeof ResizeObserver === "undefined") return

	const observer = new ResizeObserver(resize)
	observer.observe(doc.body)
}

function downloadPDF() {
	const salarySlipName = props.id
	loading.value = true
	downloadError.value = ""

	let headers = { "X-Frappe-Site-Name": window.location.hostname }
	if (window.csrf_token) {
		headers["X-Frappe-CSRF-Token"] = window.csrf_token
	}

	fetch("/api/method/hrms.api.download_salary_slip", {
		method: "POST",
		headers,
		body: new URLSearchParams({ name: salarySlipName }),
		responseType: "blob",
	})
		.then((response) => {
			if (response.ok) {
				return response.blob()
			} else {
				downloadError.value = "Failed to download PDF"
			}
		})
		.then((blob) => {
			if (!blob) return
			const blobUrl = window.URL.createObjectURL(blob)
			const link = document.createElement("a")
			link.href = blobUrl
			link.download = `${salarySlipName}.pdf`
			link.click()

			setTimeout(() => {
				window.URL.revokeObjectURL(blobUrl)
			}, 3000)
		})
		.catch((error) => {
			downloadError.value = `Failed to download PDF: ${error.message}`
		})
		.finally(() => {
			loading.value = false
		})
}
</script>
