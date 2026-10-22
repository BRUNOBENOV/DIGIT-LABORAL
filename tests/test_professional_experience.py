from pathlib import Path


def test_professional_experience_assets_are_loaded():
    root = Path(__file__).resolve().parents[1]
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    css = root / "app/static/experience.css"
    js = root / "app/static/experience.js"

    assert css.is_file()
    assert js.is_file()
    assert "path='experience.css'" in base
    assert "path='experience.js'" in base


def test_professional_list_filters_are_explicitly_local():
    root = Path(__file__).resolve().parents[1]
    script = (root / "app/static/experience.js").read_text(encoding="utf-8")

    assert 'installCardFilter(".request-grid"' in script
    assert 'installCardFilter(".notification-list"' in script
    assert "experience-filter-item-hidden" in script or "experience-filter-item-hidden" in (root / "app/static/experience.css").read_text(encoding="utf-8")


def test_workspace_navigation_uses_five_accounting_areas():
    root = Path(__file__).resolve().parents[1]
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    dashboard = (root / "app/templates/dashboard.html").read_text(encoding="utf-8")

    for area in ("Mantenimientos", "Cálculo", "Informes", "Certificados", "Utilitarios"):
        assert area in base
        assert area in dashboard

    for route in (
        "/app/companies", "/app/employees", "/app/calculations",
        "/app/liquidaciones", "/app/payrolls", "/app/vacations",
        "/app/aguinaldo", "/app/reports", "/app/compliance",
        "/app/certificates", "/app/documents", "/app/requests",
        "/app/notifications", "/app/security",
    ):
        assert route in base


def test_company_logo_upload_route_matches_company_detail_form():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    template = (root / "app/templates/company_detail.html").read_text(encoding="utf-8")
    script = (root / "app/static/v23.js").read_text(encoding="utf-8")

    assert '@app.post("/app/companies/{company_id}/logo")' in main
    assert 'action="/app/companies/{{ company.id }}/logo"' in template
    assert 'image/webp' in template
    assert "const maxBytes = 8 * 1024 * 1024;" in script
    assert "logo_saved=1" in main
    assert "logo_error=" in main


def test_logo_detector_supports_png_jpeg_and_webp():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")

    assert 'return "image/png"' in main
    assert 'return "image/jpeg"' in main
    assert 'return "image/webp"' in main


def test_runtime_logo_upload_route_has_one_effective_handler():
    from app.runtime import app

    matches = [
        route for route in app.routes
        if getattr(route, "path", None) == "/app/companies/{company_id}/logo"
        and "POST" in (getattr(route, "methods", None) or set())
    ]
    assert len(matches) == 1
    assert matches[0].endpoint.__name__ == "upload_company_logo_v23"


def test_logo_upload_limit_and_client_guidance_are_consistent():
    root = Path(__file__).resolve().parents[1]
    config = (root / "app/config.py").read_text(encoding="utf-8")
    render_yaml = (root / "render.yaml").read_text(encoding="utf-8")
    template = (root / "app/templates/company_detail.html").read_text(encoding="utf-8")
    script = (root / "app/static/v23.js").read_text(encoding="utf-8")
    route = (root / "app/ux_v23.py").read_text(encoding="utf-8")

    assert "8 * 1024 * 1024" in config
    assert 'value: "8388608"' in render_yaml
    assert "hasta 8 MB" in template
    assert "const maxBytes = 8 * 1024 * 1024;" in script
    assert '_remove_route("/app/companies/{company_id}/logo", "POST")' in route


def test_calculation_pages_render_only_the_selected_module():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    template = (root / "app/templates/calculations.html").read_text(encoding="utf-8")
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    workbench = (root / "app/templates/labor_workbench.html").read_text(encoding="utf-8")
    calculator_routes = (root / "app/calculator_routes.py").read_text(encoding="utf-8")

    assert "active_calculation_type=tipo or" in main
    assert "CalculationRecord.calculation_type == tipo" in main
    for kind in ("salary", "hours", "aguinaldo", "vacation", "notice"):
        assert f"active_calculation_type == '{kind}'" in template
        assert f'href="/app/calculations?tipo={kind}"' in base
    assert "calculation-index-grid" in template
    assert '{% if not private %}<nav class="dl-tabs"' in workbench
    assert 'tipo: str = "settlement"' in calculator_routes


def test_module_navigation_and_assets_are_versioned():
    root = Path(__file__).resolve().parents[1]
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    css = (root / "app/static/experience.css").read_text(encoding="utf-8")

    assert "v23.js') }}?v=20261022c" in base
    assert "v23.css') }}?v=20261022c" in base
    assert "experience.css') }}?v=20261022c" in base
    assert ".calculation-index-card" in css
