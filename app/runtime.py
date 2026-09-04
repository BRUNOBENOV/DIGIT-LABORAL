from __future__ import annotations

from contextlib import asynccontextmanager

from .production_entry import app
from . import ux_v23 as _ux_v23  # noqa: F401
from . import v24_data as _v24_data
from . import ux_v24 as _ux_v24  # noqa: F401

_original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _v24_lifespan(app_instance):  # noqa: ANN001
    async with _original_lifespan(app_instance):
        _v24_data.apply_v24_data_fixes()
        yield


app.router.lifespan_context = _v24_lifespan

__all__ = ["app"]
