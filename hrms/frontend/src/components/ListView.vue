<template>
	<div class="flex flex-col h-screen w-screen">
		<div class="w-full sm:w-96">
			<header
				class="flex flex-row bg-white shadow-sm py-4 px-3 items-center justify-between border-b sticky top-0 z-10"
			>
				<div class="flex flex-row items-center">
					<Button
						variant="ghost"
						class="!pl-0 hover:bg-white"
						@click="router.back()"
					>
						<FeatherIcon name="chevron-left" class="h-5 w-5" />
					</Button>
					<h2 class="text-xl font-semibold text-gray-900">{{ pageTitle }}</h2>
				</div>

				<div class="flex flex-row gap-2">
					<Button
						id="show-filter-modal"
						icon="filter"
						variant="subtle"
						:class="[
							areFiltersApplied
								? '!border !border-gray-800 !bg-white !text-gray-900 !font-semibold'
								: '',
						]"
					/>
					<router-link :to="{ name: formViewRoute }" v-slot="{ navigate }">
						<Button variant="solid" class="mr-2" @click="navigate">
							<template #prefix>
								<FeatherIcon name="plus" class="w-4" />
							</template>
							New
						</Button>
					</router-link>
				</div>
			</header>

			<div class="flex flex-col items-center mt-5 mb-7 p-4">
				<div class="w-full">
					<TabButtons
						:buttons="[{ label: tabButtons[0] }, { label: tabButtons[1] }]"
						v-model="activeTab"
					/>

					<!-- Loading Indicator -->
					<div
						v-if="documents.loading"
						class="flex h-64 items-center justify-center"
					>
						<LoadingIndicator class="w-8 h-8 text-gray-800" />
					</div>

					<div
						class="flex flex-col bg-white rounded mt-5 overflow-auto"
						v-else-if="documents.data?.length"
					>
						<div
							class="p-3.5 items-center justify-between border-b cursor-pointer"
							v-for="link in documents.data"
							:key="link.name"
						>
							<router-link
								:to="{ name: detailViewRoute, params: { id: link.name } }"
								v-slot="{ navigate }"
							>
								<component
									:is="listItemComponent[doctype]"
									:doc="link"
									:isTeamRequest="isTeamRequest"
									@click="navigate"
								/>
							</router-link>
						</div>
					</div>
					<EmptyState message="No leaves found" v-else />
				</div>
			</div>
		</div>
	</div>

	<CustomIonModal trigger="show-filter-modal">
		<!-- Filter Action Sheet -->
		<template #actionSheet>
			<ListFiltersActionSheet
				:filterConfig="filterConfig"
				@applyFilters="applyFilters"
				@clearFilters="clearFilters"
				v-model:filters="filterMap"
			/>
		</template>
	</CustomIonModal>
</template>

<script setup>
import { useRouter } from "vue-router"
import {
	inject,
	ref,
	markRaw,
	watch,
	computed,
	reactive,
	onMounted,
	onBeforeUnmount,
} from "vue"
import { modalController } from "@ionic/vue"

import { FeatherIcon, createResource, LoadingIndicator } from "frappe-ui"

import TabButtons from "@/components/TabButtons.vue"
import LeaveRequestItem from "@/components/LeaveRequestItem.vue"
import ExpenseClaimItem from "@/components/ExpenseClaimItem.vue"
import EmployeeAdvanceItem from "@/components/EmployeeAdvanceItem.vue"
import ListFiltersActionSheet from "@/components/ListFiltersActionSheet.vue"
import CustomIonModal from "@/components/CustomIonModal.vue"

const props = defineProps({
	doctype: {
		type: String,
		required: true,
	},
	fields: {
		type: Array,
		required: true,
	},
	groupBy: {
		type: String,
		required: false,
	},
	filterConfig: {
		type: Array,
		required: true,
	},
	tabButtons: {
		type: Array,
		required: true,
	},
	pageTitle: {
		type: String,
		required: true,
	},
})

const listItemComponent = {
	"Leave Application": markRaw(LeaveRequestItem),
	"Expense Claim": markRaw(ExpenseClaimItem),
	"Employee Advance": markRaw(EmployeeAdvanceItem),
}

const router = useRouter()
const socket = inject("$socket")
const employee = inject("$employee")
const filterMap = reactive({})
const activeTab = ref(props.tabButtons[0])
const areFiltersApplied = ref(false)
const appliedFilters = ref([])

// computed properties
const isTeamRequest = computed(() => {
	return activeTab.value === props.tabButtons[1]
})

const formViewRoute = computed(() => {
	return `${props.doctype.replace(/\s+/g, "")}FormView`
})

const detailViewRoute = computed(() => {
	return `${props.doctype.replace(/\s+/g, "")}DetailView`
})

const defaultFilters = computed(() => {
	const filters = []

	if (isTeamRequest.value) {
		filters.push([props.doctype, "employee", "!=", employee.data.name])
	} else {
		filters.push([props.doctype, "employee", "=", employee.data.name])
	}

	return filters
})

// helper functions
function initializeFilters() {
	props.filterConfig.forEach((filter) => {
		filterMap[filter.fieldname] = {
			condition: "=",
			value: null,
		}
	})

	appliedFilters.value = []
}
initializeFilters()

function prepareFilters() {
	let condition = ""
	let value = ""
	appliedFilters.value = []

	for (const fieldname in filterMap) {
		condition = filterMap[fieldname].condition
		// accessing .value because autocomplete returns an object instead of value
		if (typeof condition === "object" && condition !== null) {
			condition = condition.value
		}

		value = filterMap[fieldname].value
		if (condition && value)
			appliedFilters.value.push([props.doctype, fieldname, condition, value])
	}
}

function applyFilters() {
	prepareFilters()
	fetchDocumentList()
	modalController.dismiss()
	areFiltersApplied.value = appliedFilters.value.length ? true : false
}

function clearFilters() {
	initializeFilters()
	fetchDocumentList()
	modalController.dismiss()
	areFiltersApplied.value = false
}

function fetchDocumentList() {
	const filters = [[props.doctype, "docstatus", "!=", "2"]]
	filters.push(...defaultFilters.value)

	if (appliedFilters.value) filters.push(...appliedFilters.value)

	documents.submit({
		doctype: props.doctype,
		fields: props.fields,
		filters: filters,
		group_by: props.groupBy,
		order_by: `\`tab${props.doctype}\`.modified desc`,
	})
}

const documents = createResource({
	url: "frappe.desk.reportview.get",
	transform(data) {
		if (data.length === 0) {
			return []
		}

		// convert keys and values arrays to docs object
		const fields = data["keys"]
		const values = data["values"]
		const docs = values.map((value) => {
			const doc = {}
			fields.forEach((field, index) => {
				doc[field] = value[index]
			})
			return doc
		})
		return docs
	},
})

watch(
	() => activeTab.value,
	(_value) => {
		fetchDocumentList()
	},
	{ immediate: true }
)

onMounted(() => {
	socket.emit("doctype_subscribe", props.doctype)
	socket.off("list_update")
	socket.on("list_update", (data) => {
		if (data?.doctype !== props.doctype) return
		fetchDocumentList()
	})
})

onBeforeUnmount(() => {
	socket.emit("doctype_unsubscribe", props.doctype)
	socket.off("list_update")
})
</script>
