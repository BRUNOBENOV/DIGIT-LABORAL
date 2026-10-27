from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sections_is_a_maintenance_subsection():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    companies = (ROOT / "app" / "templates" / "companies.html").read_text(encoding="utf-8")
    employees = (ROOT / "app" / "templates" / "employees.html").read_text(encoding="utf-8")
    assert 'href="/app/sections"' in base
    assert "active_path.startswith('/app/sections')" in base
    assert "Secciones <span>Áreas internas</span>" in employees
    assert "Secciones <span>Áreas internas</span>" in companies


def test_sections_page_includes_filters_audit_and_safe_deactivation():
    page = (ROOT / "app" / "templates" / "sections.html").read_text(encoding="utf-8")
    for token in (
        'name="q"',
        'name="company_id"',
        'name="include_inactive"',
        "Código Sección",
        "Nombre Sección",
        "section.updated_by",
        "section.updated_at",
        "data-section-edit",
        "data-section-toggle",
        "Desactivar",
        "Reactivar",
        "X-CSRF-Token",
        "Administración",
        "Contabilidad",
        "Ventas",
        "Operaciones",
    ):
        assert token in page


def test_sections_page_and_examples_endpoint_are_registered():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert '@app.get("/app/sections", response_class=HTMLResponse)' in main
    assert '@app.post("/api/sections/examples", status_code=201)' in main
    assert 'Depends(require_roles("administrador", "contador"))' in main
    assert "Los ejemplos solo se pueden cargar" in main
