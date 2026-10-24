"""Needs the docker compose database running. Skipped unless DATABASE_URL points at it."""

import os

import pytest

psycopg = pytest.importorskip("psycopg")
pytestmark = pytest.mark.integration
URL = os.environ.get("DATABASE_URL")
skip = pytest.mark.skipif(not URL, reason="DATABASE_URL not set")


@skip
def test_reader_can_read_safe_view():
    with psycopg.connect(URL) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sales_summary_safe").fetchone()[0]
    assert count > 0


@skip
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM customers_private",
        "SELECT * FROM sales",
        "DELETE FROM sales_summary_safe",
        "UPDATE sales SET amount = 0",
        "DROP TABLE sales",
        "SELECT 1; DELETE FROM sales",
    ],
)
def test_reader_cannot_read_private_or_mutate(sql):
    with pytest.raises(psycopg.Error), psycopg.connect(URL) as conn:
        conn.execute(sql)
        conn.commit()
