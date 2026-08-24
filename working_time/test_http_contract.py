import ast
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parent


def _whitelisted_api_contract() -> dict[str, tuple[str, ...]]:
	contract: dict[str, tuple[str, ...]] = {}
	for path in sorted(PACKAGE_ROOT.rglob("*.py")):
		if path.name.startswith("test_"):
			continue
		module = ".".join(path.relative_to(PACKAGE_ROOT.parent).with_suffix("").parts)
		tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
		for node in ast.walk(tree):
			if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
				continue
			for decorator in node.decorator_list:
				if not (
					isinstance(decorator, ast.Call)
					and isinstance(decorator.func, ast.Attribute)
					and isinstance(decorator.func.value, ast.Name)
					and decorator.func.value.id == "frappe"
					and decorator.func.attr == "whitelist"
				):
					continue
				methods: tuple[str, ...] = ()
				for keyword in decorator.keywords:
					if keyword.arg == "methods":
						methods = tuple(ast.literal_eval(keyword.value))
				contract[f"{module}.{node.name}"] = methods
	return contract


class TestHttpApiContract(unittest.TestCase):
	def test_every_whitelisted_api_has_an_explicit_read_or_write_contract(self):
		expected = {
			"working_time.customer_projects.ensure_customer_project": ("POST",),
			"working_time.issues.add_issue_time": ("POST",),
			"working_time.issues.add_task_time": ("POST",),
			"working_time.issues.book_time": ("POST",),
			"working_time.issues.get_issue_time_context": (),
			"working_time.issues.get_or_create_daily_working_time": ("POST",),
			"working_time.issues.get_or_create_my_working_time": ("POST",),
			"working_time.issues.get_project_time_context": (),
			"working_time.issues.get_task_time_context": (),
			"working_time.issues.get_time_booking_context": (),
			"working_time.platform_operations.create_billing_invoice_drafts": ("POST",),
			"working_time.platform_operations.create_billing_review": ("POST",),
			"working_time.platform_operations.create_project_time_invoice_draft": ("POST",),
			"working_time.platform_operations.finalize_billing_review": ("POST",),
			"working_time.project_overview.get_project_month": (),
			"working_time.working_time.report.expected_and_actual_working_time.get_filter_values.get_employee_name": (),
			"working_time.working_time.report.expected_and_actual_working_time.get_filter_values.get_employee_working_hours": (),
		}

		self.assertEqual(_whitelisted_api_contract(), expected)

	def test_all_mutating_whitelisted_apis_are_post_only(self):
		contract = _whitelisted_api_contract()
		mutating = {
			name
			for name in contract
			if name.endswith(
				(
					"ensure_customer_project",
					"get_or_create_daily_working_time",
					"get_or_create_my_working_time",
					"book_time",
					"add_issue_time",
					"add_task_time",
					"create_billing_review",
					"create_billing_invoice_drafts",
					"create_project_time_invoice_draft",
					"finalize_billing_review",
				)
			)
		}
		self.assertEqual(len(mutating), 10)
		self.assertTrue(all(contract[name] == ("POST",) for name in mutating))
