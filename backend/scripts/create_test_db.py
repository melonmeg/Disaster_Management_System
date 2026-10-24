"""(Re)build the throw-away test database from the same SQL files.

    python scripts/create_test_db.py

Only ever drops TEST_DB_NAME, and refuses unless its name ends in "_test"
and differs from DB_NAME, so the real database cannot be touched.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import dotenv_values  # noqa: E402
from setup_db import BACKEND, admin_connection, setup  # noqa: E402
from sqlrunner import MAIN_DB  # noqa: E402


def rebuild_test_db() -> str:
    name = os.environ.get("TEST_DB_NAME", "emergency_response_management_test")
    # compare with the DB_NAME written in .env (the process env may be overridden by the tests)
    protected = {MAIN_DB, dotenv_values(BACKEND / ".env").get("DB_NAME")}
    if not name.endswith("_test") or name in protected:
        sys.exit(f"Refusing to drop {name!r}: test database name must end in '_test'")
    conn = admin_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{name}`")
        conn.commit()
    finally:
        conn.close()
    setup(name, allow_bootstrap=True)
    return name


if __name__ == "__main__":
    rebuild_test_db()
