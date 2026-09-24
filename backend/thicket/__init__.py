"""Thicket backend: field audio in, transparent detection evidence out."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def _package_version() -> str:
    try:
        return version("thicket-backend")
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        return "0.1.0"


__version__ = _package_version()
