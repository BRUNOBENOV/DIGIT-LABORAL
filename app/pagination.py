"""Shared, bounded pagination state for server-rendered directories and reports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode


PAGE_SIZES = (25, 50, 100, 200)


def normalize_page_size(value: int, default: int = 100) -> int:
    return value if value in PAGE_SIZES else default


def _parameters(values: dict[str, Any]) -> dict[str, str]:
    return {
        key: ("true" if value is True else str(value).strip())
        for key, value in values.items()
        if value is not None and value is not False and str(value).strip() != ""
    }


@dataclass
class Pagination:
    path: str
    total: int
    page: int = 1
    page_size: int = 100
    filters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.total = max(0, int(self.total))
        self.page_size = normalize_page_size(self.page_size)
        self.page = min(max(1, int(self.page)), self.pages)
        self.filters = _parameters(self.filters)

    @property
    def sizes(self) -> tuple[int, ...]:
        return PAGE_SIZES

    @property
    def pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def start(self) -> int:
        return self.offset + 1 if self.total else 0

    @property
    def end(self) -> int:
        return min(self.offset + self.page_size, self.total)

    @property
    def numbers(self) -> list[int | None]:
        selected = sorted({1, self.pages, *range(max(1, self.page - 2), min(self.pages, self.page + 2) + 1)})
        result: list[int | None] = []
        for number in selected:
            if result:
                previous = result[-1]
                if number - previous == 2:
                    result.append(previous + 1)
                elif number - previous > 2:
                    result.append(None)
            result.append(number)
        return result

    def url(self, page: int | None = None, page_size: int | None = None, **filters: Any) -> str:
        values = _parameters({**self.filters, **filters})
        values.update(page=str(self.page if page is None else page), page_size=str(page_size or self.page_size))
        return f"{self.path}?{urlencode(values)}"
