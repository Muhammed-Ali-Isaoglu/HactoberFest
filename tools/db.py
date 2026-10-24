"""Constrained sales executor. Fixed SQL templates only; no caller-supplied SQL or identifiers."""

from typing import Protocol

from core.models import SalesAggregateArgs

# group_by is mapped through this dict, so it can never inject SQL.
SQL_BY_GROUP = {
    "day": (
        "SELECT sale_date::text AS key, SUM(amount)::float AS total, SUM(quantity) AS units"
        " FROM sales_summary_safe WHERE sale_date BETWEEN %s AND %s"
        " GROUP BY sale_date ORDER BY sale_date LIMIT %s"
    ),
    "product": (
        "SELECT product AS key, SUM(amount)::float AS total, SUM(quantity) AS units"
        " FROM sales_summary_safe WHERE sale_date BETWEEN %s AND %s"
        " GROUP BY product ORDER BY total DESC LIMIT %s"
    ),
}


class SalesExecutor(Protocol):
    def aggregate(self, args: SalesAggregateArgs) -> list[dict]: ...


class PostgresSalesExecutor:
    """Connects as the read-only reader role. The URL is never returned to callers or logged."""

    def __init__(self, url: str) -> None:
        self._url = url

    def aggregate(self, args: SalesAggregateArgs) -> list[dict]:
        import psycopg

        sql = SQL_BY_GROUP[args.group_by]
        with psycopg.connect(self._url, options="-c default_transaction_read_only=on") as conn:
            rows = conn.execute(sql, (args.start_date, args.end_date, args.limit)).fetchall()
        return [{"key": r[0], "total": r[1], "units": int(r[2])} for r in rows]

    def snapshot(self) -> dict:
        """Checksum of every sales value the reader can see. Any UPDATE, DELETE or INSERT changes it."""
        import psycopg

        sql = (
            "SELECT COUNT(*), COALESCE(SUM(amount), 0)::text,"
            " md5(COALESCE(string_agg(concat_ws('|', sale_date, product, region, quantity, amount),"
            " ',' ORDER BY sale_date, product, region, quantity, amount), ''))"
            " FROM sales_summary_safe"
        )
        with psycopg.connect(self._url) as conn:
            count, total, digest = conn.execute(sql).fetchone()
        return {"rows": count, "total": total, "checksum": digest}


def synthetic_rows() -> list[dict]:
    """Same 150 rows as db/init/002_seed.sql, so memory and Postgres backends agree."""
    from datetime import date, timedelta

    products = ["Widget", "Gadget", "Gizmo", "Doohickey"]
    regions = ["North", "South", "East", "West"]
    rows = []
    for g in range(1, 151):
        rows.append(
            {
                "sale_date": date(2026, 9, 1) + timedelta(days=g % 30),
                "product": products[g % 4],
                "region": regions[g % 3],
                "quantity": 1 + g % 7,
                "amount": round(((g * 37) % 500 + 20), 2),
            }
        )
    return rows


class StaticSalesExecutor:
    """Deterministic in-memory executor for offline tests, the evaluation harness and the demo."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def aggregate(self, args: SalesAggregateArgs) -> list[dict]:
        in_range = [r for r in self._rows if args.start_date <= r["sale_date"] <= args.end_date]
        totals: dict[str, dict] = {}
        for r in in_range:
            key = str(r["sale_date"]) if args.group_by == "day" else r["product"]
            bucket = totals.setdefault(key, {"key": key, "total": 0.0, "units": 0})
            bucket["total"] += float(r["amount"])
            bucket["units"] += int(r["quantity"])
        ordered = (
            sorted(totals.values(), key=lambda b: b["key"])
            if args.group_by == "day"
            else sorted(totals.values(), key=lambda b: -b["total"])
        )
        return ordered[: args.limit]

    def snapshot(self) -> dict:
        import hashlib

        lines = sorted(
            f"{r['sale_date']}|{r['product']}|{r['region']}|{r['quantity']}|{r['amount']}"
            for r in self._rows
        )
        total = sum(float(r["amount"]) for r in self._rows)
        return {
            "rows": len(self._rows),
            "total": f"{total:.2f}",
            "checksum": hashlib.md5("\n".join(lines).encode()).hexdigest(),
        }
