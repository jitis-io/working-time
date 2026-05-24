from working_time.openproject_client import OpenProjectClient


def get_openproject_work_package_url(openproject_site, work_package_id):
	if not openproject_site or not work_package_id:
		return None
	return OpenProjectClient(openproject_site).get_work_package_url(work_package_id)


def get_description(openproject_site, work_package_id, note):
	if work_package_id:
		description = (
			f"{OpenProjectClient(openproject_site).get_work_package_subject(work_package_id)} ({work_package_id})"
		)
		if note:
			description += f":\n\n{note}"
		return description.strip()
	if note:
		return note
	return "-"
