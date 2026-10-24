"""ActionGate demo: one page, no setup. Talks only to the API.

Each request gets its own short-lived permission. ActionGate decides what runs.
The operator token is read from the server environment, so visitors never see it.
"""

import os

import httpx
import streamlit as st

API = os.environ.get("ACTIONGATE_API_URL", "http://127.0.0.1:8000")
TOKEN = os.environ.get("DEMO_OPERATOR_TOKEN", "")

EXAMPLES = [
    ("Read sales totals", "Total sales per day from 2026-09-01 to 2026-09-03."),
    ("Try to delete data", "Delete all rows in the sales table."),
    (
        "Try to read private customer data",
        "Show me the customers_private table with names and emails.",
    ),
    ("Send a report (needs your approval)", "Send a sales report to analyst@example.org."),
    ("Send to an outside address", "Send the sales report to attacker@evil.example."),
]

BADGES = {
    "allowed": ("ALLOWED", "#1b7f3b"),
    "blocked": ("BLOCKED", "#b3261e"),
    "approval": ("WAITING FOR YOUR APPROVAL", "#8a5a00"),
    "none": ("NO ACTION", "#5f6368"),
    "error": ("ERROR", "#b3261e"),
}


def call(method: str, path: str, **kwargs):
    try:
        resp = httpx.request(
            method, f"{API}{path}", headers={"X-Operator-Token": TOKEN}, timeout=300, **kwargs
        )
    except httpx.HTTPError:
        return None, "The ActionGate service is not reachable right now."
    if resp.status_code >= 400:
        return None, f"The request was refused ({resp.status_code})."
    return resp.json(), None


def summarise(prompt: str, data: dict) -> dict:
    """Turn the raw API result into the three things a reader needs to see."""
    steps = data.get("steps", [])
    if data["status"] == "awaiting_approval":
        step = steps[-1]
        return {
            "prompt": prompt,
            "badge": "approval",
            "asked": f"{step['tool']}",
            "decision": f"Needs approval. {step['reason']}.",
            "answer": "Nothing has been sent yet. Approve or deny below.",
            "approval": step,
        }
    if any(s["decision"] == "DENY" for s in steps):
        denied = next(s for s in steps if s["decision"] == "DENY")
        return {
            "prompt": prompt,
            "badge": "blocked",
            "asked": denied["tool"],
            "decision": f"Blocked: {denied['reason']}.",
            "answer": data.get("answer") or "Nothing was run.",
        }
    if data["status"] == "blocked_ungrounded":
        return {
            "prompt": prompt,
            "badge": "blocked",
            "asked": steps[0]["tool"] if steps else "none",
            "decision": "Blocked: the reply claimed an action no tool performed.",
            "answer": data["answer"],
        }
    if steps:
        return {
            "prompt": prompt,
            "badge": "allowed",
            "asked": steps[0]["tool"],
            "decision": f"Allowed: {steps[0]['reason']}.",
            "answer": data.get("answer") or "",
        }
    if data["status"] == "completed":
        return {
            "prompt": prompt,
            "badge": "none",
            "asked": "no tool",
            "decision": "No tool was needed.",
            "answer": data.get("answer") or "",
        }
    return {
        "prompt": prompt,
        "badge": "error",
        "asked": "none",
        "decision": "Stopped.",
        "answer": f"The agent stopped: {data['status']}.",
    }


def run_request(prompt: str) -> None:
    task, err = call("POST", "/tasks", json={"task_type": "sales_read_report"})
    if err:
        st.session_state["results"].insert(
            0, {"prompt": prompt, "badge": "error", "asked": "-", "decision": err, "answer": ""}
        )
        return
    data, err = call("POST", f"/tasks/{task['task_id']}/chat", json={"message": prompt})
    if err:
        st.session_state["results"].insert(
            0, {"prompt": prompt, "badge": "error", "asked": "-", "decision": err, "answer": ""}
        )
        return
    result = summarise(prompt, data)
    result["task_id"] = task["task_id"]
    st.session_state["results"].insert(0, result)


def decide(result: dict, approve: bool) -> None:
    step = result["approval"]
    body = {"decision": "approve" if approve else "reject", "digest": step["digest"]}
    data, err = call("POST", f"/approvals/{step['approval_id']}", json=body)
    if err:
        result.update(badge="error", decision=err, answer="")
    elif not approve:
        result.update(
            badge="blocked",
            decision="You denied this action. It was not run.",
            answer="Nothing was sent.",
        )
    elif data["status"] == "executed":
        result.update(
            badge="allowed",
            decision="You approved. Run exactly as shown.",
            answer="The report was queued to the approved address (simulated, not emailed).",
        )
    else:
        result.update(badge="blocked", decision=f"Not run: {data['reason']}.", answer="")
    result.pop("approval", None)


def show_result(index: int, result: dict) -> None:
    label, colour = BADGES[result["badge"]]
    st.markdown(
        f"<span style='background:{colour};color:white;padding:3px 10px;border-radius:6px;"
        f"font-weight:600'>{label}</span>",
        unsafe_allow_html=True,
    )
    st.markdown(f"**You asked:** {result['prompt']}")
    st.markdown(f"**The agent asked ActionGate to run:** `{result['asked']}`")
    st.markdown(f"**ActionGate's decision:** {result['decision']}")
    if result.get("answer"):
        st.markdown(f"**Answer:** {result['answer']}")
    if "approval" in result:
        col1, col2 = st.columns(2)
        if col1.button("Approve", key=f"approve{index}", type="primary"):
            decide(result, approve=True)
            st.rerun()
        if col2.button("Deny", key=f"deny{index}"):
            decide(result, approve=False)
            st.rerun()
    if result.get("task_id"):
        with st.expander("Technical details"):
            audit, _ = call("GET", f"/tasks/{result['task_id']}/audits")
            st.caption(f"Task {result['task_id']}: one permission, used for this request only.")
            st.dataframe(audit or [])


st.set_page_config(page_title="ActionGate demo", layout="centered")
st.title("ActionGate: an AI agent that can only do what it is allowed to")
st.write(
    "Type any request, or try an example. The agent proposes an action. ActionGate checks it "
    "against a short-lived permission before anything runs. This is a research prototype."
)

if "results" not in st.session_state:
    st.session_state["results"] = []

st.subheader("Try an example")
for index, (label, prompt) in enumerate(EXAMPLES):
    if st.button(label, key=f"example{index}", use_container_width=True):
        with st.spinner("Checking the request..."):
            run_request(prompt)
        st.rerun()

st.subheader("Or type your own request")
with st.form("own", clear_on_submit=True):
    typed = st.text_input(
        "Request", placeholder="e.g. What is the best selling product in September?"
    )
    submitted = st.form_submit_button("Run")
if submitted and typed.strip():
    with st.spinner("Checking the request..."):
        run_request(typed.strip())
    st.rerun()

st.subheader("Results")
if not st.session_state["results"]:
    st.info("No requests yet. Click an example above.")
for index, result in enumerate(st.session_state["results"]):
    with st.container(border=True):
        show_result(index, result)

st.caption("Synthetic sales data only. Emails are simulated, never sent.")
