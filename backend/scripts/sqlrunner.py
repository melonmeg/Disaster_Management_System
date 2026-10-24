"""Execute .sql files (including DELIMITER blocks) through PyMySQL.

The SQL files are written for the database `emergency_response_management`
so they can be run directly in the MySQL CLI; `target_db` rewrites that name
so the same files can build the test database.

A statement preceded by a line `-- EXPECT ERROR` is a deliberate failure in a
demo script: its error is caught and reported instead of stopping the run
(in the MySQL CLI use `mysql --force` or run those lines one by one).
"""
import re
from pathlib import Path

import pymysql

MAIN_DB = "emergency_response_management"
EXPECT_ERROR = "-- EXPECT ERROR"


def split_statements(sql: str) -> list[tuple[str, bool]]:
    """Return [(statement, expect_error), ...]."""
    statements, buf, delimiter, expect = [], [], ";", False
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER "):
            delimiter = stripped.split(None, 1)[1]
            continue
        if not buf and stripped.upper().startswith(EXPECT_ERROR):
            expect = True
            continue
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        if delimiter == ";":
            # drop a trailing "-- comment" so "SELECT 1;  -- note" still ends the statement
            line = re.sub(r"\s--\s.*$", "", line)
            stripped = line.strip()
        buf.append(line)
        if stripped.endswith(delimiter):
            text = "\n".join(buf).rstrip()
            statements.append((text[: -len(delimiter)].strip(), expect))
            buf, expect = [], False
    if "".join(buf).strip():
        statements.append(("\n".join(buf).strip(), expect))
    return [(s, e) for s, e in statements if s]


def run_sql_file(conn, path: Path, target_db: str = MAIN_DB, verbose: bool = False) -> dict:
    """Run every statement; returns counts. Raises if an unexpected statement fails
    or a statement marked EXPECT ERROR succeeds."""
    sql = Path(path).read_text(encoding="utf-8")
    if target_db != MAIN_DB:
        sql = re.sub(rf"\b{MAIN_DB}\b", target_db, sql)
    stats = {"statements": 0, "expected_errors": 0}
    with conn.cursor() as cur:
        for stmt, expect_error in split_statements(sql):
            stats["statements"] += 1
            try:
                cur.execute(stmt)
                rows = cur.fetchall() if cur.description else ()
                while cur.nextset():  # drain extra result sets (e.g. CALL)
                    pass
            except pymysql.MySQLError as exc:
                if not expect_error:
                    raise RuntimeError(f"{Path(path).name}: statement failed: {stmt[:120]!r}: {exc}") from exc
                stats["expected_errors"] += 1
                if verbose:
                    print(f"  expected error -> {exc.args}")
                continue
            if expect_error:
                raise RuntimeError(f"{Path(path).name}: statement was expected to fail: {stmt[:120]!r}")
            if verbose and rows:
                print(f"  {stmt.splitlines()[0][:80]}  -> {len(rows)} row(s)")
    conn.commit()
    return stats
