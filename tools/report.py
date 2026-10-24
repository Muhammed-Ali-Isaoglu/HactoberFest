"""Local report outbox. Never sends real mail; every queued report is marked simulated_sent."""

import json
import time
from pathlib import Path

from core.models import ReportPreviewArgs, ReportSendArgs


def preview(args: ReportPreviewArgs) -> dict:
    return {"title": args.title, "body": args.body, "status": "preview_only"}


class LocalOutbox:
    def __init__(self, path: Path) -> None:
        self._path = path

    def queue(self, args: ReportSendArgs) -> dict:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.time(),
            "title": args.title,
            "recipient": args.recipient,
            "body_chars": len(args.body),
            "status": "simulated_sent",
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return {"status": "simulated_sent", "recipient": args.recipient}
