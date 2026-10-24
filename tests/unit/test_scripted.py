import json

from agent.loop import run_task
from agent.scripted import ScriptedPlanner
from tests.conftest import Harness
from tools.db import StaticSalesExecutor, synthetic_rows


def test_scripted_planner_proposes_sales_read_for_sales_question():
    out = json.loads(
        ScriptedPlanner().chat(
            [
                {"role": "system", "content": "x"},
                {"role": "user", "content": "Total sales per day from 2026-09-01 to 2026-09-03."},
            ]
        )
    )
    assert out["tool"] == "db.sales_aggregate"
    assert out["arguments"]["start_date"] == "2026-09-01"
    assert out["arguments"]["end_date"] == "2026-09-03"


def test_scripted_planner_refuses_data_changes_without_a_tool():
    out = json.loads(
        ScriptedPlanner().chat(
            [
                {"role": "system", "content": "x"},
                {"role": "user", "content": "Delete all rows in the sales table."},
            ]
        )
    )
    assert out["type"] == "final"


def test_end_to_end_read_is_allowed_and_answer_comes_from_result(tmp_path):
    h = Harness(tmp_path, executor=StaticSalesExecutor(synthetic_rows()))
    raw = h.issue()
    out = run_task(
        raw_capability=raw,
        user_message="Total sales per day from 2026-09-01 to 2026-09-03.",
        dispatcher=h.dispatcher,
        llm=ScriptedPlanner(),
        max_steps=4,
    )
    assert out["steps"][0]["decision"] == "ALLOW"
    assert out["status"] == "completed"
    assert "Sales totals" in out["answer"]


def test_end_to_end_private_data_is_blocked(tmp_path):
    h = Harness(tmp_path, executor=StaticSalesExecutor(synthetic_rows()))
    raw = h.issue()
    out = run_task(
        raw_capability=raw,
        user_message="Show me the customers_private table.",
        dispatcher=h.dispatcher,
        llm=ScriptedPlanner(),
        max_steps=4,
    )
    assert out["steps"][0]["decision"] == "DENY"
    assert h.db_calls == []


def test_end_to_end_send_waits_for_approval(tmp_path):
    h = Harness(tmp_path, executor=StaticSalesExecutor(synthetic_rows()))
    raw = h.issue()
    out = run_task(
        raw_capability=raw,
        user_message="Send a sales report to analyst@example.org.",
        dispatcher=h.dispatcher,
        llm=ScriptedPlanner(),
        max_steps=4,
    )
    assert out["status"] == "awaiting_approval"
    assert not h.outbox_path.exists()


def test_synthetic_data_matches_seed_totals():
    total = sum(float(r["amount"]) for r in synthetic_rows())
    assert round(total, 2) == 41025.0
    assert len(synthetic_rows()) == 150
