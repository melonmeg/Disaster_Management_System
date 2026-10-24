"""Set up the MySQL side of the project (run with the DBA account from .env).

    python scripts/setup_db.py --bootstrap     # first time: create DB + sample data, then everything below
    python scripts/setup_db.py                 # re-apply functions/views/procedures/triggers/grants

Steps
  1. (--bootstrap, only if the database does not exist) run sql/00_base_tables.sql,
     emergency_response.sql and emergency_response_demo_data.sql.
  2. One-time migration sql/01_* (tracked in schema_migrations).
  3. Re-runnable files sql/02_* .. sql/06_*.
  4. Create/refresh the least-privilege MySQL login accounts and give them their roles.
  5. Seed the initial application users (bcrypt hashes) if they do not exist.
Nothing here deletes or rewrites existing rows.
"""
import argparse
import os
import sys
from pathlib import Path

import bcrypt
import pymysql
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SQL = ROOT / "sql"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlrunner import run_sql_file  # noqa: E402

load_dotenv(BACKEND / ".env")

MIGRATIONS = ["01_auth_constraints_indexes.sql"]
REPEATABLE = [
    "02_functions.sql",
    "03_views.sql",
    "04_procedures.sql",
    "05_triggers.sql",
    "06_roles_privileges.sql",
]
# env prefix -> MySQL role
DB_ACCOUNTS = {
    "DB_AUTH": "erm_role_auth",
    "DB_ADMIN": "erm_role_admin",
    "DB_DISPATCHER": "erm_role_dispatcher",
    "DB_RESPONDER": "erm_role_responder",
}
# (env prefix, role, responder_id from the sample data)
SEED_USERS = [
    ("SEED_ADMIN", "admin", None),
    ("SEED_DISPATCHER", "dispatcher", 1),  # Aarav Sharma, Dispatcher
    ("SEED_RESPONDER", "responder", 2),    # Diya Nair, Police Officer on Police Unit 12
]


def admin_connection(database=None):
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ["MYSQL_ADMIN_USER"],
        password=os.environ["MYSQL_ADMIN_PASSWORD"],
        database=database,
        autocommit=False,
    )


def database_exists(name: str) -> bool:
    conn = admin_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (name,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def bootstrap(db: str) -> None:
    conn = admin_connection()
    try:
        run_sql_file(conn, SQL / "00_base_tables.sql", db)
        conn.select_db(db)
        run_sql_file(conn, ROOT / "emergency_response.sql", db)
        run_sql_file(conn, ROOT / "emergency_response_demo_data.sql", db)
    finally:
        conn.close()
    print(f"  created database {db} with schema and sample data")


def apply_sql(db: str) -> None:
    conn = admin_connection(db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name VARCHAR(100) PRIMARY KEY,"
                " applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
            cur.execute("SELECT name FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}
        for name in MIGRATIONS:
            if name in applied:
                continue
            run_sql_file(conn, SQL / name, db)
            with conn.cursor() as cur:
                cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (name,))
            conn.commit()
            print(f"  migration applied: {name}")
        for name in REPEATABLE:
            run_sql_file(conn, SQL / name, db)
            print(f"  applied: {name}")
    finally:
        conn.close()


def create_accounts() -> None:
    conn = admin_connection()
    try:
        with conn.cursor() as cur:
            for prefix, role in DB_ACCOUNTS.items():
                user = os.environ[f"{prefix}_USER"]
                password = os.environ[f"{prefix}_PASSWORD"]
                cur.execute("CREATE USER IF NOT EXISTS %s@'localhost' IDENTIFIED BY %s", (user, password))
                cur.execute("ALTER USER %s@'localhost' IDENTIFIED BY %s", (user, password))
                cur.execute(f"GRANT {role} TO %s@'localhost'", (user,))
                cur.execute("SET DEFAULT ROLE ALL TO %s@'localhost'", (user,))
                print(f"  MySQL account {user}@localhost -> {role}")
        conn.commit()
    finally:
        conn.close()


def seed_app_users(db: str) -> None:
    conn = admin_connection(db)
    try:
        with conn.cursor() as cur:
            for prefix, role, responder_id in SEED_USERS:
                username = os.environ.get(f"{prefix}_USERNAME")
                password = os.environ.get(f"{prefix}_PASSWORD")
                if not username or not password:
                    continue
                cur.execute("SELECT 1 FROM app_users WHERE username = %s", (username,))
                if cur.fetchone():
                    continue
                password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                cur.execute(
                    "INSERT INTO app_users (username, password_hash, role, responder_id) VALUES (%s, %s, %s, %s)",
                    (username, password_hash, role, responder_id),
                )
                print(f"  app user '{username}' ({role}) created")
        conn.commit()
    finally:
        conn.close()


def setup(db: str, allow_bootstrap: bool) -> None:
    print(f"Setting up {db}")
    if not database_exists(db):
        if not allow_bootstrap:
            sys.exit(f"Database {db} does not exist. Re-run with --bootstrap to create it.")
        bootstrap(db)
    apply_sql(db)
    create_accounts()
    seed_app_users(db)
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default=os.environ.get("DB_NAME", "emergency_response_management"))
    parser.add_argument("--bootstrap", action="store_true", help="create the database if it does not exist")
    args = parser.parse_args()
    setup(args.database, args.bootstrap)
