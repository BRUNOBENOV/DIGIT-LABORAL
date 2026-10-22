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
    assert "const maxBytes = 2 * 1024 * 1024;" in script
    assert "logo_saved=1" in main
    assert "logo_error=" in main


def test_logo_detector_supports_png_jpeg_and_webp():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")

    assert 'return "image/png"' in main
    assert 'return "image/jpeg"' in main
    assert 'return "image/webp"' in main
