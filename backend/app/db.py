"""MySQL access.

Every request uses the MySQL account that matches the caller's application
role (erm_admin / erm_dispatcher / erm_responder), so MySQL privileges are a
second, independent layer of access control behind the API checks.
"""
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from .config import settings


def connect(account: str) -> pymysql.connections.Connection:
    user, password = settings.db_account(account)
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=user,
        password=password,
        database=settings.db_name,
        cursorclass=DictCursor,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=5,
    )


class Database:
    def __init__(self, conn):
        self.conn = conn

    def all(self, sql: str, params=None) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def one(self, sql: str, params=None) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def scalar(self, sql: str, params=None):
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def execute(self, sql: str, params=None) -> tuple[int, int]:
        """Run a write; returns (lastrowid, rowcount)."""
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.lastrowid, cur.rowcount

    def call(self, procedure: str, args: tuple = ()) -> list:
        """CALL a stored procedure; returns the final values of all (IN/OUT) arguments."""
        with self.conn.cursor() as cur:
            cur.callproc(procedure, args)
            while cur.nextset():
                pass
            if not args:
                return []
            names = ", ".join(f"@_{procedure}_{i}" for i in range(len(args)))
            cur.execute(f"SELECT {names}")
            return list(cur.fetchone().values())

    @contextmanager
    def transaction(self):
        """BEGIN ... COMMIT, or ROLLBACK if anything inside raises."""
        self.conn.begin()
        try:
            yield self
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise


@contextmanager
def open_db(account: str):
    conn = connect(account)
    try:
        yield Database(conn)
    finally:
        conn.close()
