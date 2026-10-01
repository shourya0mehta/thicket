"""Opaque identifiers.

Ids are random hex with a type prefix and are validated with a strict,
anchored regex before they are ever used to build a filesystem path or a
query, so values like ``../../etc/passwd`` can never reach the disk layer.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Literal

Prefix = Literal[
    "ana",
    "rec",
    "prv",
    "site",
    # platform
    "user",
    "org",
    "inv",
    "rcd",
    "dep",
    "job",
    "alr",
    "ntf",
    "rpt",
    "file",
    "ses",
]

_TOKEN_HEX = 24
_PREFIXES = (
    "ana",
    "rec",
    "prv",
    "site",
    "user",
    "org",
    "inv",
    "rcd",
    "dep",
    "job",
    "alr",
    "ntf",
    "rpt",
    "file",
    "ses",
)
_ID_RE = {p: re.compile(rf"\A{p}_[0-9a-f]{{{_TOKEN_HEX}}}\Z") for p in _PREFIXES}
RUN_ID_RE = re.compile(r"\Arun_[0-9a-f]{16}\Z")
EVENT_ID_RE = re.compile(r"\Aevt_[0-9a-f]{16}\Z")

# The implicit local workspace (AUTH_MODE=disabled) has fixed ids so a
# database upgraded from the single-user build keeps pointing at them.
LOCAL_USER_ID = "user_" + "0" * _TOKEN_HEX
LOCAL_ORG_ID = "org_" + "0" * _TOKEN_HEX


def new_id(prefix: Prefix) -> str:
    return f"{prefix}_{secrets.token_hex(_TOKEN_HEX // 2)}"


def is_valid_id(value: object, prefix: Prefix) -> bool:
    return isinstance(value, str) and bool(_ID_RE[prefix].match(value))


def is_valid_event_id(value: object) -> bool:
    return isinstance(value, str) and bool(EVENT_ID_RE.match(value))


def model_run_id(analysis_id: str, adapter_key: str) -> str:
    """Deterministic per (analysis, adapter), so reprocessing yields stable event ids."""
    digest = hashlib.sha1(f"{analysis_id}|{adapter_key}".encode()).hexdigest()[:16]
    return f"run_{digest}"
