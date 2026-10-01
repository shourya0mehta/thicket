"""Model registry: initialized adapter instances with an explicit lifecycle.

1. :func:`build_registry` creates adapter *instances* (never classes) from
   settings and registers them. Nothing heavy happens yet.
2. :meth:`ModelRegistry.start_loading` loads every adapter once, in a
   background thread by default. Each adapter moves from ``loading`` to
   ``ready`` or ``unavailable`` (with a reason); ``disabled`` adapters stay
   disabled.
3. :meth:`ModelRegistry.get` validates a request: ``unknown_model`` for a
   key that is not registered, ``model_unavailable`` for a disabled or failed
   adapter. A ``loading`` adapter is returned; jobs call
   :meth:`ModelRegistry.require_ready` to wait for it.

The frog/insect adapter is always registered so clients can see it and why
it is off.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from pathlib import Path

from thicket.api.schemas import ErrorCode, ModelInfo
from thicket.config import Settings
from thicket.errors import ThicketError
from thicket.models.base import AcousticModelAdapter
from thicket.models.birdnet import BirdNETAdapter, SharedBirdNET
from thicket.models.birdnet_runtime import BirdNETUnavailable, Label
from thicket.models.frog_insect import FrogInsectAdapter

log = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, AcousticModelAdapter] = {}
        self._thread: threading.Thread | None = None
        self._label_index: dict[str, Label] | None = None
        self._label_lock = threading.Lock()

    # -- registration -------------------------------------------------------
    def register(self, adapter: AcousticModelAdapter) -> None:
        if isinstance(adapter, type):
            raise TypeError("register an adapter instance, not a class")
        if adapter.key in self._adapters:
            raise ValueError(f"model {adapter.key!r} is already registered")
        prepare = getattr(adapter, "prepare", None)
        if callable(prepare):
            prepare()
        self._adapters[adapter.key] = adapter

    def keys(self) -> list[str]:
        return list(self._adapters)

    def __contains__(self, key: object) -> bool:
        return key in self._adapters

    def adapters(self) -> list[AcousticModelAdapter]:
        return list(self._adapters.values())

    # -- lifecycle ----------------------------------------------------------
    def start_loading(self, background: bool = True) -> None:
        def _run() -> None:
            for adapter in self._adapters.values():
                adapter.load()

        if not background:
            _run()
            return
        if self._thread is None:
            self._thread = threading.Thread(target=_run, name="thicket-model-loader", daemon=True)
            self._thread.start()

    def wait_all(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # -- lookup -------------------------------------------------------------
    def lookup(self, key: str) -> AcousticModelAdapter:
        adapter = self._adapters.get(key)
        if adapter is None:
            known = ", ".join(self._adapters) or "none"
            raise ThicketError(
                ErrorCode.unknown_model,
                f"Unknown model '{key[:40]}'. Available models: {known}.",
                detail={"model": key[:40], "available": list(self._adapters)},
            )
        return adapter

    def get(self, key: str) -> AcousticModelAdapter:
        adapter = self.lookup(key)
        status = adapter.status()
        if status == "disabled":
            raise ThicketError(
                ErrorCode.model_unavailable,
                adapter.unavailable_reason() or f"{adapter.name} is disabled.",
                status_code=422,
                detail={"model": key, "status": status},
            )
        if status == "unavailable":
            raise ThicketError(
                ErrorCode.model_unavailable,
                f"{adapter.name} is unavailable: {adapter.unavailable_reason() or 'unknown reason'}",
                status_code=503,
                detail={"model": key, "status": status},
            )
        return adapter

    def default_models(self, preferred: tuple[str, ...] = ("birdnet", "frog_insect")) -> list[str]:
        """Models used when a request names none: every preferred model that is
        not disabled or unavailable (a loading model counts; the run waits for it)."""
        out = [
            k
            for k in preferred
            if k in self._adapters and self._adapters[k].status() not in ("disabled", "unavailable")
        ]
        return out or [k for k in preferred if k in self._adapters][:1]

    def require_ready(self, key: str, timeout: float | None) -> AcousticModelAdapter:
        adapter = self.get(key)
        if adapter.status() == "loading":
            waiter = getattr(adapter, "wait_settled", None)
            if waiter is not None:
                waiter(timeout)
        if not adapter.is_ready():
            self.get(key)  # raises with the settled reason
            raise ThicketError(
                ErrorCode.model_unavailable,
                f"{adapter.name} is still loading. Try again shortly.",
                detail={"model": key, "status": adapter.status()},
            )
        return adapter

    # -- presentation -------------------------------------------------------
    def info(self, adapter: AcousticModelAdapter) -> ModelInfo:
        return ModelInfo(
            key=adapter.key,
            name=adapter.name,
            version=adapter.version,
            taxa=list(adapter.taxon_scope),
            status=adapter.status(),  # type: ignore[arg-type]
            experimental=adapter.experimental,
            required_sample_rate_hz=adapter.required_sample_rate_hz,
            window_seconds=adapter.window_seconds,
            license=adapter.license,
            model_card_url=getattr(adapter, "model_card_url", None),
            description=adapter.description,
            unavailable_reason=adapter.unavailable_reason(),
        )

    def infos(self) -> list[ModelInfo]:
        return [self.info(a) for a in self._adapters.values()]

    def statuses(self) -> dict[str, str]:
        return {k: a.status() for k, a in self._adapters.items()}

    # -- label resolution (review corrections) ------------------------------
    def _labels(self) -> Iterable[Label]:
        for adapter in self._adapters.values():
            shared = getattr(adapter, "shared", None)
            if isinstance(adapter, BirdNETAdapter) and shared is not None and adapter.is_ready():
                try:
                    yield from shared.get().labels
                except BirdNETUnavailable:
                    continue
            head = getattr(adapter, "head", None)
            if head is not None:
                yield from head.labels

    def resolve_label(self, text: str | None) -> Label | None:
        """Match a reviewer's label to a known label (scientific, common or raw; case-insensitive)."""
        if not text:
            return None
        with self._label_lock:
            index = self._label_index
            if index is None:
                index = {}
                for lab in self._labels():
                    for k in (lab.raw, lab.scientific_name, lab.common_name):
                        index.setdefault(k.strip().casefold(), lab)
                if all(a.status() != "loading" for a in self._adapters.values()):
                    self._label_index = index
        return index.get(text.strip().casefold())


def packaged_frog_insect_head() -> Path | None:
    """The head shipped inside the package, if this build includes one."""
    p = Path(__file__).resolve().parent / "data" / "frog_insect_v1.npz"
    return p if p.is_file() else None


def build_registry(settings: Settings) -> ModelRegistry:
    shared = SharedBirdNET(settings.birdnet_model_dir)
    registry = ModelRegistry()
    registry.register(BirdNETAdapter(shared, enabled=settings.birdnet_enabled))
    registry.register(
        FrogInsectAdapter(
            shared,
            model_path=settings.frog_insect_model_path or packaged_frog_insect_head(),
            enabled=settings.frog_insect_enabled,
        )
    )
    return registry
