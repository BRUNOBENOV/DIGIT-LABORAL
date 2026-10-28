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
        "/app/liquidaciones", "/app/vacations", "/app/aguinaldo",
        "/app/reports", "/app/compliance", "/app/certificates",
        "/app/documents", "/app/requests", "/app/notifications",
        "/app/security",
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

    # The active module has one canonical entrypoint per requested submodule.
    for route in (
        '/app/liquidaciones?tipo=salary',
        '/app/aguinaldo',
        '/app/vacations',
        '/app/calculations?tipo=notice',
    ):
        assert f'href="{route}"' in base
    assert "calculation-index-grid" in template
    assert '{% if not private %}<nav class="dl-tabs"' in workbench
    assert 'tipo: str = "settlement"' in calculator_routes


def test_module_navigation_and_assets_are_versioned():
    root = Path(__file__).resolve().parents[1]
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    css = (root / "app/static/experience.css").read_text(encoding="utf-8")

    assert "v23.js') }}?v=20261023b" in base
    assert "v23.css') }}?v=20261022c" in base
    assert "experience.css') }}?v=20261027a" in base
    assert ".calculation-index-card" in css


def test_sidebar_uses_requested_brand_navy_and_original_white_logo():
    root = Path(__file__).resolve().parents[1]
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    sidebar_css = (root / "app/static/sidebar-brand-theme-2624.css").read_text(encoding="utf-8")
    white_logo = (root / "app/static/branding/digit-laboral-logo-blanco.svg").read_text(encoding="utf-8")

    assert "sidebar-brand-theme-2624.css" in base and "v=20261028a" in base
    assert "background:#05256d!important" in sidebar_css
    assert "background:#05256d!important" in sidebar_css.split("@media(max-width:860px)")[1]
    assert 'src="/static/branding/digit-laboral-logo-blanco.svg?v=20261028b"' in base
    # The white variant embeds and recolors the exact original wordmark, rather than redrawing it.
    assert "digit-laboral-logo-267.webp" in white_logo
    assert 'href="data:image/webp;base64,' in white_logo
    assert 'filter="url(#original-wordmark-white)"' in white_logo
    assert "<feColorMatrix" in white_logo
    assert 'M10 10 H112' not in white_logo  # no separately redrawn replacement mark


def test_official_brand_identity_assets_are_used_across_the_product():
    root = Path(__file__).resolve().parents[1]
    static = root / "app/static/branding"
    base = (root / "app/templates/base.html").read_text(encoding="utf-8")
    login = (root / "app/templates/login.html").read_text(encoding="utf-8")
    public_nav = (root / "app/templates/labor_public_nav.html").read_text(encoding="utf-8")
    public_footer = (root / "app/templates/labor_public_footer.html").read_text(encoding="utf-8")
    css = (root / "app/static/brand-identity.css").read_text(encoding="utf-8")

    mark = (static / "digit-laboral-mark.webp").read_bytes()
    wordmark = (static / "digit-laboral-wordmark.webp").read_bytes()
    favicon = (static / "digit-laboral-favicon.svg").read_text(encoding="utf-8")

    assert mark.startswith(b"RIFF") and mark[8:12] == b"WEBP"
    assert wordmark.startswith(b"RIFF") and wordmark[8:12] == b"WEBP"
    assert "#0B2D78" in favicon
    assert "brand-identity.css" in base and "v=20261023b" in base
    assert "digit-laboral-logo-267.webp" in base
    assert "digit-laboral-logo-267.webp" in login
    assert "digit-laboral-logo-267.webp" in public_nav
    assert "digit-laboral-logo-267.webp" in public_footer
    assert ".official-wordmark" in css and "--accent:#0B2D78" in css


def test_company_logo_adjustment_controls_are_persistent_and_previewed():
    root = Path(__file__).resolve().parents[1]
    model = (root / "app/models.py").read_text(encoding="utf-8")
    migration = (root / "alembic/versions/0008_company_logo_presentation.py").read_text(encoding="utf-8")
    handler = (root / "app/ux_v23.py").read_text(encoding="utf-8")
    template = (root / "app/templates/company_detail.html").read_text(encoding="utf-8")
    script = (root / "app/static/v23.js").read_text(encoding="utf-8")
    css = (root / "app/static/brand-identity.css").read_text(encoding="utf-8")

    for setting in ("logo_fit", "logo_scale", "logo_alignment", "logo_background"):
        assert setting in model
        assert setting in migration
        assert setting in handler
        assert f'name="{setting}"' in template

    assert "data-logo-settings-form" in template
    assert "data-logo-reset" in template
    assert "updateLogoPreviews" in script
    assert ".logo-adjuster-preview" in css
    assert ".home-module-card:nth-child(5n+2)" in css
    assert ".page-header{" in css
