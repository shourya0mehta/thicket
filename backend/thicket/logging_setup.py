"""Structured logging.

Logs are one JSON object per line. Context goes in ``extra=``, for example
``log.info("analysis completed", extra={"analysis_id": aid, "stage_timings_ms": t})``.

Privacy rule: never log audio, filenames, notes, coordinates or other raw
user metadata. Log ids, sizes, timings and error codes.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
    | {"message", "asctime", "taskName", "color_message"}
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


_configured = False


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Install one stdout handler on the root logger (idempotent)."""
    global _configured
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.set_name("thicket")
    for h in list(root.handlers):
        if h.get_name() == "thicket":
            root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)
    # Route uvicorn through the same handler; our middleware writes access logs.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
    _configured = True
