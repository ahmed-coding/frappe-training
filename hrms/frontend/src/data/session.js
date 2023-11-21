import { computed, reactive } from "vue"
import { createResource } from "frappe-ui"
import { userResource } from "./user"
import { employeeResource } from "./employee"
import router from "@/router"

export function sessionUser() {
	let cookies = new URLSearchParams(document.cookie.split("; ").join("&"))
	let _sessionUser = cookies.get("user_id")
	if (_sessionUser === "Guest") {
		_sessionUser = null
	}
	return _sessionUser
}

export const session = reactive({
	login: createResource({
		url: "login",
		makeParams({ email, password }) {
			return {
				usr: email,
				pwd: password,
			}
		},
		onSuccess(data) {
			userResource.reload()
			employeeResource.reload()

			session.user = sessionUser()
			session.login.reset()
			router.replace(data.default_route || "/")
		},
	}),
	logout: createResource({
		url: "logout",
		onSuccess() {
			userResource.reset()
			employeeResource.reset()

			session.user = sessionUser()
			router.replace({ name: "Login" })
			window.location.reload()
		},
	}),
	user: sessionUser(),
	isLoggedIn: computed(() => !!session.user),
})
