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
    assert 'include "module_subnav.html"' in base
    assert "ui-system-264.js" in base
    for token in (
        "--ui-navy:#0D1B2A",
        "--ui-primary:#2563EB",
        "--ui-bg:#F9FAFB",
        "--ui-text:#111827",
        ".ui-module-nav",
        ".ui-section-card",
        ".ui-table-toolbar",
        "prefers-reduced-motion:reduce",
    ):
        assert token in css
    for token in ("enhanceForms", "enhanceTables", "aria-live", "aria-sort"):
        assert token in js


def test_secondary_navigation_renders_for_major_authenticated_modules():
    with TestClient(app) as client:
        _login(client)
        cases = [
            ("/app/calculations", "Subsecciones de cálculo laboral"),
            ("/app/calculations?tipo=salary", "Salarios"),
            ("/app/reports", "Subsecciones de informes"),
            ("/app/certificates", "Subsecciones de certificados y documentos"),
            ("/app/requests", "Subsecciones de utilitarios"),
            ("/app/calendar", "Subsecciones de utilitarios"),
            ("/app/payrolls", "Subsecciones de cálculo laboral"),
            ("/app/vacations", "Subsecciones de cálculo laboral"),
            ("/app/aguinaldo", "Subsecciones de cálculo laboral"),
            ("/app/compliance", "Subsecciones de informes"),
            ("/app/documents", "Subsecciones de certificados y documentos"),
            ("/app/users", "Usuarios y permisos"),
            ("/app/parameters", "Parámetros"),
        ]
        for path, expected in cases:
            response = client.get(path)
            assert response.status_code == 200, f"{path}: {response.status_code} {response.text[:300]}"
            assert expected in response.text, f"no secondary navigation in {path}"


def test_reusable_jinja_macros_are_documented_and_loaded_by_the_navigation_partial():
    macro = (ROOT / "app" / "templates" / "components" / "ui.html").read_text(encoding="utf-8")
    nav = (ROOT / "app" / "templates" / "module_subnav.html").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "UI_SYSTEM_V264.md").read_text(encoding="utf-8")
    assert "macro tab_nav" in macro
    assert "macro section_card" in macro
    assert "macro inline_help" in macro
    assert 'from "components/ui.html" import tab_nav' in nav
    assert "FastAPI + Jinja2" in docs
    assert "no implementa una SPA" in docs
