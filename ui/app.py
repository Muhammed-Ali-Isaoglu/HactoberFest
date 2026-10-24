"""Streamlit demo. Talks only to the live API; shows real decisions, not simulated output.

Demo only: the operator token is typed in the sidebar and is not a secure login.
"""

import os

import httpx
import streamlit as st

API = st.sidebar.text_input(
    "API URL", os.environ.get("ACTIONGATE_API_URL", "http://127.0.0.1:8000")
)
TOKEN = st.sidebar.text_input("Demo operator token", type="password")
st.title("ActionGate demo")
st.caption("Research / demo security prototype, not production hardened.")

HEADERS = {"X-Operator-Token": TOKEN}


def call(method: str, path: str, **kwargs):
    try:
        resp = httpx.request(method, f"{API}{path}", headers=HEADERS, timeout=120, **kwargs)
    except httpx.HTTPError as exc:
        st.error(f"API unreachable: {type(exc).__name__}")
        return None
    if resp.status_code >= 400:
        st.error(f"{resp.status_code}: {resp.json().get('detail', 'error')}")
        return None
    return resp.json()


task_type = st.selectbox("Task template", ["sales_read_report", "sales_read_only"])
if st.button("Start task (issues scoped capability)"):
    st.session_state["task"] = call("POST", "/tasks", json={"task_type": task_type})

task = st.session_state.get("task")
if task:
    st.info(
        f"Task {task['task_id']} · principal {task['principal']} · template {task['task_type']}"
    )
    message = st.text_input("Ask the analyst", "Total sales per day from 2026-09-01 to 2026-09-07")
    if st.button("Send"):
        st.session_state["last"] = call(
            "POST", f"/tasks/{task['task_id']}/chat", json={"message": message}
        )
    last = st.session_state.get("last")
    if last:
        st.subheader(f"Agent status: {last['status']}")
        st.write(last.get("answer") or "")
        st.dataframe(last.get("steps", []))

    pending = call("GET", f"/tasks/{task['task_id']}/pending-approvals") or []
    for item in pending:
        st.warning(f"Pending {item['tool']}: {item['args_json']}")
        col1, col2 = st.columns(2)
        if col1.button("Approve exact action", key=f"a{item['approval_id']}"):
            st.write(
                call(
                    "POST",
                    f"/approvals/{item['approval_id']}",
                    json={"decision": "approve", "digest": item["digest"]},
                )
            )
        if col2.button("Reject", key=f"r{item['approval_id']}"):
            st.write(
                call(
                    "POST",
                    f"/approvals/{item['approval_id']}",
                    json={"decision": "reject", "digest": item["digest"]},
                )
            )

    st.subheader("Audit trail")
    st.dataframe(call("GET", f"/tasks/{task['task_id']}/audits") or [])
    if st.button("Revoke capability"):
        st.write(call("POST", f"/tasks/{task['task_id']}/revoke"))
