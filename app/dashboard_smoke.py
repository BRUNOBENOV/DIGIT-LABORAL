from __future__ import annotations

import logging

from .main import templates
from .runtime import app

logger = logging.getLogger("digit.dashboard_smoke")

TEMPLATES = (
    "base.html",
    "dashboard.html",
    "companies.html",
    "company_detail.html",
    "employees.html",
    "payroll_detail.html",
    "calculations.html",
    "vacations.html",
)

REQUIRED_ROUTES = {
    ("GET", "/app"),
    ("GET", "/app/companies"),
    ("POST", "/app/companies"),
    ("GET", "/app/companies/{company_id}"),
    ("GET", "/app/companies/{company_id}/logo"),
    ("POST", "/app/companies/{company_id}/logo"),
    ("POST", "/app/companies/{company_id}/branding"),
    ("GET", "/app/employees"),
    ("POST", "/app/employees"),
    ("POST", "/app/employees/{employee_id}/status"),
    ("GET", "/app/payrolls"),
    ("POST", "/app/payrolls/{payroll_id}/lines/{line_id}"),
    ("GET", "/app/calculations"),
    ("POST", "/app/calculations"),
    ("GET", "/app/vacations"),
    ("POST", "/app/vacations"),
    ("GET", "/app/requests"),
    ("GET", "/app/certificates"),
    ("GET", "/app/compliance"),
    ("GET", "/app/documents"),
    ("GET", "/app/reports"),
    ("GET", "/app/calendar"),
    ("GET", "/app/labor-code"),
    ("GET", "/app/security"),
    ("GET", "/app/export/studio.zip"),
}


def run() -> None:
    for name in TEMPLATES:
        templates.env.get_template(name)

    available: set[tuple[str, str]] = set()
    for route in app.router.routes:
        path = getattr(route, "path", "")
        for method in getattr(route, "methods", set()) or set():
            available.add((method.upper(), path))

    missing = sorted(REQUIRED_ROUTES - available)
    if missing:
        formatted = ", ".join(f"{method} {path}" for method, path in missing)
        raise RuntimeError(f"Dashboard smoke test failed; missing routes: {formatted}")

    logger.warning(
        "Dashboard smoke test OK: %s templates compiled, %s critical routes present",
        len(TEMPLATES),
        len(REQUIRED_ROUTES),
    )


if __name__ == "__main__":
    run()
