# Copyright (c) 2023, ALYF GmbH and contributors
# For license information, please see license.txt


import json

import frappe
import requests
from frappe import _
from requests.auth import HTTPBasicAuth


class OpenProjectNotFoundError(RuntimeError):
	pass


class OpenProjectTransientError(RuntimeError):
	pass


OPENPROJECT_REQUEST_TIMEOUT = 30
TRANSIENT_HTTP_STATUSES = {408, 425, 429}


def _normalize_base_url(site_url: str) -> str:
	raw = (site_url or "").strip()
	if not raw:
		frappe.throw(_("OpenProject Site URL is required"))
	if not raw.startswith(("http://", "https://")):
		raw = f"https://{raw}"
	raw = raw.rstrip("/")
	if raw.endswith("/api/v3"):
		raw = raw[: -len("/api/v3")]
	return raw


class OpenProjectClient:
	def __init__(self, openproject_site: str) -> None:
		site = frappe.get_doc("OpenProject Site", openproject_site)

		self.base_url = _normalize_base_url(site.site_url)
		self.api_url = f"{self.base_url}/api/v3"
		self.session = requests.Session()
		self.session.auth = HTTPBasicAuth(site.username, site.get_password(fieldname="api_token"))
		self.session.headers = {"Accept": "application/json"}

	def get(self, path: str, params=None):
		url = path if path.startswith(("http://", "https://")) else f"{self.api_url}{path}"
		try:
			response = self.session.get(url, params=params, timeout=OPENPROJECT_REQUEST_TIMEOUT)
		except (requests.ConnectionError, requests.Timeout) as exc:
			raise OpenProjectTransientError(f"{url}: {exc}") from exc

		try:
			response.raise_for_status()
		except requests.HTTPError:
			try:
				error_text = json.loads(response.text)
			except json.JSONDecodeError:
				error_text = {}

			error_message = (
				error_text.get("message")
				or error_text.get("errorMessage")
				or (error_text.get("errorMessages") or [None])[0]
				or "Something went wrong."
			)

			if response.status_code == 404:
				raise OpenProjectNotFoundError(f"{url}: {_(error_message)}") from None
			if response.status_code in TRANSIENT_HTTP_STATUSES or response.status_code >= 500:
				raise OpenProjectTransientError(f"{url}: {_(error_message)}") from None

			frappe.throw(f"{url}: {_(error_message)}")

		return response.json()

	def get_work_package_subject(self, work_package_id: str) -> str:
		return self.get(f"/work_packages/{work_package_id}").get("subject")

	def get_work_package_url(self, work_package_id: str) -> str:
		return f"{self.base_url}/work_packages/{work_package_id}"
