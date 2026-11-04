"""Controles de regresión para la interfaz compartida de DIGIT-LABORAL.

Estas comprobaciones son estáticas y no sustituyen pruebas visuales en navegador.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app/templates/base.html"
STATIC = ROOT / "app/static"


def test_all_shared_css_and_js_use_the_same_release_cache_key():
    html = TEMPLATE.read_text(encoding="utf-8")
    tags = re.findall(r'<(?:link|script)\b[^>]*>', html)
    assets = [tag for tag in tags if "url_for('static', path='" in tag]
    assert len(assets) >= 40
    assert all("?v={{ app_version }}" in tag for tag in assets)
    assert 'digit-laboral-favicon.svg?v={{ app_version }}' in html


def test_keyboard_can_skip_main_navigation_on_authenticated_views():
    html = TEMPLATE.read_text(encoding="utf-8")
    css = (STATIC / "ui-system-264.css").read_text(encoding="utf-8")
    assert 'class="app-skip-link" href="#app-main-content"' in html
    assert '<main class="main-content" id="app-main-content" tabindex="-1">' in html
    assert ".app-skip-link:focus-visible" in css
    assert "z-index:2000" in css


def test_salary_summary_notes_are_at_least_11px_and_responsive():
    css = (STATIC / "calculator-quick.css").read_text(encoding="utf-8")
    for selector in [
        ".dl-quick .dl-field .dl-salary-suggestion",
        ".dl-quick .dl-facts dt",
        ".dl-quick .dl-summary-footnote",
    ]:
        assert re.search(re.escape(selector) + r"\{font-size:11px", css)
    assert "@media(max-width:900px)" in css
    assert ".dl-quick .dl-calculator-layout{grid-template-columns:1fr}" in css


def test_post_forms_in_critical_modules_contain_csrf_fields():
    templates = (
        "base.html", "employees.html", "companies.html", "payrolls.html",
        "certificates.html", "official_certificates.html", "compliance.html",
        "salary_import.html", "calculations.html", "labor_workbench.html",
        "liquidation_saved.html", "calculation_operations.html",
        "salary_settlement_detail.html", "medical_exams.html",
        "vacations.html", "requests.html", "documents.html",
        "employee_delete.html", "calendar.html", "admin.html",
        "ai_assistant.html", "security.html", "post_import_reactivation.html",
    )
    for filename in templates:
        html = (ROOT / "app/templates" / filename).read_text(encoding="utf-8")
        forms = re.findall(
            r'<form\b[^>]*method\s*=\s*["\']post["\'][^>]*>[\s\S]*?</form>',
            html, re.IGNORECASE,
        )
        for form in forms:
            assert "csrf_token" in form, f"Formulario POST sin CSRF en {filename}"


def test_all_html_templates_compile_with_registered_jinja_filters():
    """Detectar errores de sintaxis incluso en pantallas no abiertas por la suite."""
    from app import main as core
    names = core.templates.env.list_templates(extensions=["html"])
    assert len(names) >= 70
    for name in names:
        core.templates.env.get_template(name)


def test_shared_assets_reference_files_that_exist_in_static_folder():
    html = TEMPLATE.read_text(encoding="utf-8")
    references = re.findall(r"url_for\('static', path='([^']+)'\)", html)
    assert len(references) >= 40
    for path in references:
        assert (STATIC / path).is_file(), f"Recurso estático inexistente: {path}"
