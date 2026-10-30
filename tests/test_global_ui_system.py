from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def _login(client: TestClient) -> None:
    page = client.get("/login")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert page.status_code == 200 and match
    response = client.post(
        "/login",
        data={
            "email": "admin@digitlaboral.com.py",
            "password": settings.demo_admin_password,
            "csrf_token": match.group(1),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_global_design_assets_are_loaded_after_the_existing_theme():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "ui-system-264.css").read_text(encoding="utf-8")
    js = (ROOT / "app" / "static" / "ui-system-264.js").read_text(encoding="utf-8")
    positions = [
        base.find("theme-261.css"),
        base.find("maintenance-workspace-263.css"),
        base.find("ui-system-264.css"),
    ]
    assert all(index >= 0 for index in positions)
    assert positions == sorted(positions)
    assert 'include "module_subnav.html"' not in base
    assert "ui-system-264.js" in base
    for obsolete_patch in (
        "sidebar-contrast-265.css",
        "sidebar-active-269.css",
        "home-label-fix-2613.css",
        "sidebar-brand-transparent-2617.css",
        "sidebar-brand-theme-2624.css",
    ):
        assert obsolete_patch not in base
    for token in (
        "--ui-navy:#05256D",
        "--ui-primary:#1D4ED8",
        "--ui-bg:#F2F5FA",
        "--ui-text:#172033",
        ".ui-section-card",
        ".ui-table-toolbar",
        "prefers-reduced-motion:reduce",
    ):
        assert token in css
    for token in ("enhanceForms", "enhanceTables", "aria-live", "aria-sort"):
        assert token in js


def test_workspace_sidebar_is_the_single_global_navigation():
    with TestClient(app) as client:
        _login(client)
        home = client.get("/app")
        assert home.status_code == 200
        assert 'id="modernMobileNav"' in home.text
        sidebar = home.text.split('id="modernMobileNav"', 1)[1].split("</nav>", 1)[0]
        for label in (
            "Mantenimientos",
            "Cálculo",
            "Informes",
            "Certificados",
            "Utilitarios",
        ):
            assert label in sidebar
        for href in (
            "/app/calculations?tipo=salary",
            "/app/payrolls",
            "/app/medical-exams",
            "/app/notifications",
        ):
            assert f'href="{href}"' in sidebar
        assert sidebar.count('href="/app/medical-exams"') == 1
        assert "/app/certificates/official" not in sidebar

        calculation_start = sidebar.find('<span class="workspace-group-name">Cálculo</span>')
        calculation_end = sidebar.find("</details>", calculation_start)
        maintenance_start = sidebar.find('<span class="workspace-group-name">Mantenimientos</span>')
        maintenance_end = sidebar.find("</details>", maintenance_start)
        assert calculation_start >= 0 and calculation_end > calculation_start
        assert "/app/medical-exams" not in sidebar[calculation_start:calculation_end]
        assert "/app/medical-exams" in sidebar[maintenance_start:maintenance_end]

        cases = [
            "/app/calculations",
            "/app/calculations?tipo=salary",
            "/app/reports",
            "/app/certificates",
            "/app/requests",
            "/app/calendar",
            "/app/payrolls",
            "/app/vacations",
            "/app/aguinaldo",
            "/app/compliance",
            "/app/documents",
            "/app/users",
            "/app/parameters",
            "/app/medical-exams",
        ]
        for path in cases:
            response = client.get(path)
            assert response.status_code == 200, f"{path}: {response.status_code} {response.text[:300]}"
            assert "ui-module-nav" not in response.text


def test_reusable_component_macros_are_documented():
    macro = (ROOT / "app" / "templates" / "components" / "ui.html").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "VISUAL_SYSTEM_V2648.md").read_text(encoding="utf-8")
    assert "macro section_card" in macro
    assert "macro inline_help" in macro
    assert "FastAPI + Jinja2" in docs
    assert "cinco áreas" in docs
    assert "no modifica" in docs

