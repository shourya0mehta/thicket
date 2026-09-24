"""Load-state bookkeeping shared by every adapter.

States: ``loading`` (registered, not yet loaded), ``ready``, ``unavailable``
(tried and failed, with a reason) and ``disabled`` (switched off by
configuration, with a reason). Loading happens once; waiters block on an
event rather than polling.
"""

from __future__ import annotations

import logging
import threading
from typing import Literal

Status = Literal["ready", "loading", "unavailable", "disabled"]

log = logging.getLogger(__name__)


class AdapterLifecycle:
    key: str = ""

    def __init__(self) -> None:
        self._status: Status = "loading"
        self._reason: str | None = None
        self._settled = threading.Event()
        self._load_lock = threading.Lock()

    def prepare(self) -> None:
        """Settle configuration-driven state (``disabled``) without loading anything.

        Called at registration so a disabled model is reported as such at once,
        not as ``loading`` until the background loader reaches it.
        """
        with self._load_lock:
            if self._settled.is_set():
                return
            reason = self._disabled_reason()
            if reason:
                self._status, self._reason = "disabled", reason
                self._settled.set()

    # -- protocol -----------------------------------------------------------
    def status(self) -> Status:
        return self._status

    def unavailable_reason(self) -> str | None:
        return self._reason

    def is_ready(self) -> bool:
        return self._status == "ready"

    def load(self) -> None:
        """Load once. Never raises: failures become ``unavailable`` with a reason."""
        with self._load_lock:
            if self._settled.is_set():
                return
            try:
                disabled = self._disabled_reason()
                if disabled:
                    self._status, self._reason = "disabled", disabled
                else:
                    self._load()
                    self._status, self._reason = "ready", None
            except Exception as exc:  # noqa: BLE001 - reported through status
                self._status = "unavailable"
                self._reason = self._describe_failure(exc)
                log.warning(
                    "model unavailable",
                    extra={"model": self.key, "reason": self._reason},
                    exc_info=not isinstance(exc, RuntimeError),
                )
            finally:
                self._settled.set()
            if self._status == "ready":
                log.info("model ready", extra={"model": self.key})

    def wait_settled(self, timeout: float | None = None) -> Status:
        self._settled.wait(timeout)
        return self._status

    # -- hooks --------------------------------------------------------------
    def _disabled_reason(self) -> str | None:
        return None

    def _load(self) -> None:
        raise NotImplementedError

    def _describe_failure(self, exc: Exception) -> str:
        return str(exc) or exc.__class__.__name__
