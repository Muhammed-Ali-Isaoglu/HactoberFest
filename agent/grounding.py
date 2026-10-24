"""Post-hoc check that a final answer does not claim effects no tool produced.

Deterministic keyword check, not a semantic judge. A sentence is flagged when it uses a
claim word and has no negation. Negated sentences ("I did not delete anything") pass.
Known limit: a claim phrased without these words, or a negation far from the claim word,
is not caught.
"""

import re

WRITE_WORDS = {
    "deleted",
    "delete",
    "removed",
    "cleared",
    "updated",
    "inserted",
    "dropped",
    "truncated",
}
SEND_WORDS = {"sent", "emailed", "delivered"}
NEGATIONS = {"not", "no", "never", "cannot", "unable", "didn't", "don't", "wasn't", "couldn't"}


def _sentences(text: str) -> list[set[str]]:
    parts = re.split(r"[.!?;\n]+", text.lower())
    return [set(re.findall(r"[a-z']+", part)) for part in parts if part.strip()]


def check(answer: str, steps: list[dict]) -> list[str]:
    warnings: list[str] = []
    sent = any(s["tool"] == "report.send" and s["status"] == "executed" for s in steps)
    write_claim = send_claim = False
    for words in _sentences(answer):
        if words & NEGATIONS:
            continue
        write_claim = write_claim or bool(words & WRITE_WORDS)
        send_claim = send_claim or bool(words & SEND_WORDS)
    if write_claim:
        warnings.append("answer claims a data change, but no write tool exists")
    if send_claim and not sent:
        warnings.append("answer claims delivery without an executed report.send")
    return warnings
