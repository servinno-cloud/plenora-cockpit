import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[2]


class MonitoringSqlContractTests(unittest.TestCase):
    def test_role_is_read_only_and_only_grants_django_migrations(self):
        sql = (ROOT / "deploy/sql/create-monitoring-role.sql").read_text().lower()
        for attribute in (
            "login",
            "nosuperuser",
            "nocreatedb",
            "nocreaterole",
            "noinherit",
            "noreplication",
            "default_transaction_read_only = on",
            "grant connect on database",
            "grant usage on schema public",
            "grant select on table public.django_migrations",
        ):
            self.assertIn(attribute, sql)
        self.assertNotIn("alembic_version", sql)
        self.assertNotIn("password", sql)
        self.assertNotIn("\\prompt", sql)
        self.assertTrue(sql.lstrip().startswith("begin;"))
        self.assertIn("commit;", sql)
        grants = re.findall(r"grant select on table\s+([^\s;]+)", sql)
        self.assertEqual(grants, ["public.django_migrations"])
        for business_table in ("people", "person", "shift", "leave", "mail"):
            self.assertNotIn(business_table, sql)


if __name__ == "__main__":
    unittest.main()
