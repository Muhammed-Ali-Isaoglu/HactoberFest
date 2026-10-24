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


class StaticSalesExecutor:
    """Deterministic in-memory executor for offline tests and the evaluation harness."""

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
