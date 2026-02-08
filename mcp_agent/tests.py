from django.test import SimpleTestCase

from mcp_agent.sql_guard import GuardConfig, validate_and_rewrite


class SqlGuardTests(SimpleTestCase):
    def setUp(self) -> None:
        self.cfg = GuardConfig(allow_schemas={"public"}, max_limit=50)

    def test_rejects_non_select(self):
        with self.assertRaises(ValueError):
            validate_and_rewrite("UPDATE public.sales SET city = 'X'", self.cfg)

    def test_forbids_select_star(self):
        with self.assertRaises(ValueError):
            validate_and_rewrite("SELECT * FROM public.sales LIMIT 5", self.cfg)

    def test_clamps_limit(self):
        sql = validate_and_rewrite("SELECT id FROM public.sales LIMIT 9999", self.cfg)
        self.assertIn("LIMIT 50", sql.upper())

    def test_schema_allowlist(self):
        with self.assertRaises(ValueError):
            validate_and_rewrite("SELECT id FROM secret.table_one", self.cfg)
