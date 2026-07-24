from __future__ import annotations

import re
from hashlib import sha1
from typing import Any

import frappe
import requests
from frappe import _

KEYCLOAK_TIMEOUT = 30


def customer_group_name(customer: str, prefix: str) -> str:
	key = re.sub(r"[^a-z0-9]+", "-", customer.lower()).strip("-")
	return f"{prefix or 'customer-'}{key or 'unknown'}-{sha1(customer.encode()).hexdigest()[:8]}"


class KeycloakAdminClient:
	def __init__(self):
		settings = frappe.get_single("Platform Operations Settings")
		self.base_url = (settings.keycloak_base_url or "").rstrip("/")
		self.realm = settings.keycloak_realm or ""
		self.client_id = settings.keycloak_client_id or ""
		self.client_secret = settings.get_password("keycloak_client_secret") or ""
		if not all((self.base_url, self.realm, self.client_id, self.client_secret)):
			frappe.throw(_("Keycloak service settings are incomplete."))
		self.session = requests.Session()
		self.session.headers["Accept"] = "application/json"
		self.session.headers["Authorization"] = f"Bearer {self._access_token()}"

	def _access_token(self) -> str:
		url = f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token"
		try:
			response = requests.post(
				url,
				data={
					"grant_type": "client_credentials",
					"client_id": self.client_id,
					"client_secret": self.client_secret,
				},
				timeout=KEYCLOAK_TIMEOUT,
			)
			response.raise_for_status()
		except requests.RequestException as exc:
			frappe.throw(_("Could not obtain Keycloak service token: {0}").format(exc))
		return response.json()["access_token"]

	def _url(self, path: str) -> str:
		return f"{self.base_url}/admin/realms/{self.realm}{path}"

	def _request(self, method: str, path: str, **kwargs):
		try:
			response = self.session.request(method, self._url(path), timeout=KEYCLOAK_TIMEOUT, **kwargs)
		except requests.RequestException as exc:
			frappe.throw(_("Keycloak request failed: {0}").format(exc))
		if response.status_code == 404:
			return None
		try:
			response.raise_for_status()
		except requests.RequestException as exc:
			frappe.throw(_("Keycloak request failed: {0}").format(exc))
		if not response.content:
			return {}
		return response.json()

	def find_group(self, name: str) -> dict[str, Any] | None:
		groups = (
			self._request("GET", "/groups", params={"search": name, "briefRepresentation": "false"}) or []
		)
		return next((group for group in groups if group.get("name") == name), None)

	def ensure_group(self, name: str) -> dict[str, Any]:
		group = self.find_group(name)
		if group:
			return group
		self._request("POST", "/groups", json={"name": name})
		group = self.find_group(name)
		if not group:
			frappe.throw(_("Keycloak group {0} could not be created.").format(name))
		return group

	def ensure_realm_role(self, name: str) -> dict[str, Any]:
		role = self._request("GET", f"/roles/{name}")
		if role:
			return role
		self._request("POST", "/roles", json={"name": name})
		role = self._request("GET", f"/roles/{name}")
		if not role:
			frappe.throw(_("Keycloak realm role {0} could not be created.").format(name))
		return role

	def assign_realm_role_to_group(self, group_id: str, role: dict[str, Any]) -> None:
		self._request("POST", f"/groups/{group_id}/role-mappings/realm", json=[role])

	def group_members(self, group_id: str) -> list[dict[str, Any]]:
		return self._request("GET", f"/groups/{group_id}/members", params={"max": 1000}) or []

	def remove_user_from_group(self, user_id: str, group_id: str) -> None:
		self._request("DELETE", f"/users/{user_id}/groups/{group_id}")

	def add_user_to_group(self, user_id: str, group_id: str) -> None:
		self._request("PUT", f"/users/{user_id}/groups/{group_id}")
