from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _calculation_sidebar_block() -> str:
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    marker = '<span class="workspace-group-name">Cálculo</span>'
    marker_at = base.index(marker)
    start = base.rfind('<details class="workspace-nav-group"', 0, marker_at)
    end = base.index("</details>", marker_at) + len("</details>")
    return base[start:end]


def test_calculation_sidebar_has_one_global_entry_for_each_work_area():
    block = _calculation_sidebar_block()
    expected = [
        'href="/app/calculations?tipo=salary">Salario</a>',
        'href="/app/liquidaciones?tipo=salary">Liquidación de haberes</a>',
        'href="/app/liquidaciones?tipo=settlement">Liquidación final</a>',
        'href="/app/payrolls">Nóminas mensuales</a>',
        'href="/app/calculations?tipo=hours">Horas y recargos</a>',
        'href="/app/calculations?tipo=notice">Preaviso</a>',
        'href="/app/calculations">Calculadoras laborales</a>',
        'href="/app/aguinaldo">Aguinaldo</a>',
        'href="/app/vacations">Vacaciones</a>',
        'href="/app/calculation-operations?tipo=advance">Anticipos</a>',
        'href="/app/calculation-operations?tipo=discipline">Amonestaciones / Suspensión / Permisos</a>',
        'href="/app/calculation-operations?tipo=telegram">Telegrama colacionado</a>',
        'href="/app/employee-history">Histórico funcionario</a>',
    ]
    assert block.count('class="workspace-nav-link') == len(expected)
    assert all(item in block for item in expected)
    assert "/app/medical-exams" not in block
    for removed in (
        "Panel de Cálculo",
        "Calculadora de horas y recargos",
        "Calculadora de aguinaldo",
        "Calculadora de vacaciones",
        "Cobertura de períodos",
    ):
        assert removed not in block


def test_calculation_pages_do_not_render_a_duplicate_global_secondary_navigation():
    root = ROOT / "app" / "templates"
    base = (root / "base.html").read_text(encoding="utf-8")
    assert "module_subnav.html" not in base
    assert not (root / "module_subnav.html").exists()
    ui_css = (ROOT / "app" / "static" / "ui-system-264.css").read_text(encoding="utf-8")
    assert ".ui-module-nav" not in ui_css


def test_salary_entry_uses_the_selected_calculation_and_keeps_the_professional_workbench():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    cards = (ROOT / "app" / "templates" / "calculations.html").read_text(encoding="utf-8")
    workbench = (ROOT / "app" / "templates" / "labor_workbench.html").read_text(encoding="utf-8")
    fields = (ROOT / "app" / "calculator_fields.py").read_text(encoding="utf-8")
    assert 'href="/app/calculations?tipo=salary">Salario</a>' in _calculation_sidebar_block()
    assert 'href="/app/liquidaciones?tipo=salary{% if selected_company %}' in cards
    assert "Volver al módulo Cálculo" in workbench
    assert 'href="/app/payrolls"' not in workbench
    assert 'SALARY_EXTRAS = group("Haberes adicionales", REMUNERATIVE_EXTRA_FIELDS, False)' in fields
    salary_fields = fields.split('"salary": [', 1)[1].split('"settlement": [', 1)[0]
    assert "SALARY_EXTRAS" in salary_fields
    assert "Horas ordinarias nocturnas · adicional del 30 %" in fields
    assert "Horas extraordinarias diurnas · mínimo 50 % (total 150 %)" in fields
    assert "Horas extraordinarias nocturnas · recargo 100 % (total 200 %)" in fields
    assert "Horas trabajadas en feriado · adicional 100 %" in fields
    assert "Ajuste manual de horas extras" in fields
    assert "overtime-total-preview" in workbench
    assert "Base IPS revisada" in fields
    assert "Otros descuentos" in fields


def test_calculation_operation_template_does_not_include_removed_subnavigation():
    root = ROOT / "app" / "templates"
    operation_template = (root / "calculation_operations.html").read_text(encoding="utf-8")
    assert "module_subnav.html" not in operation_template
    assert not (root / "module_subnav.html").exists()

    # Catch stale includes even when the referenced template is conditionally rendered.
    for template in root.rglob("*.html"):
        assert "module_subnav.html" not in template.read_text(encoding="utf-8"), template.name
