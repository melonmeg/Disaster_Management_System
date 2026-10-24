"""The viva demo scripts must run end-to-end (deliberate failures marked -- EXPECT ERROR)."""
from pathlib import Path

import pytest

from conftest import TEST_DB
from setup_db import admin_connection
from sqlrunner import run_sql_file

SQL = Path(__file__).resolve().parents[2] / "sql"


@pytest.mark.parametrize("name", ["07_queries_demo.sql", "08_transactions_demo.sql", "09_privileges_demo.sql"])
def test_demo_script_runs(test_database, name):
    conn = admin_connection(TEST_DB)
    try:
        stats = run_sql_file(conn, SQL / name, TEST_DB)
    finally:
        conn.close()
    assert stats["statements"] > 0
