from __future__ import annotations

from .production_entry import app
from . import ux_v23 as _ux_v23  # noqa: F401

__all__ = ["app"]
