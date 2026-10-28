from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _calculation_sidebar_block() -> str:
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    marker = '<span class="workspace-group-name">Cálculo</span>'
    marker_at = base.index(marker)
    start = base.rfind('<details class="workspace-nav-group"', 0, marker_at)
    end = base.index("</details>", marker_at) + len("</details>")
    return base[start:end]


def test_calculation_sidebar_exposes_only_the_ten_requested_submodules():
    block = _calculation_sidebar_block()
    expected = [
        'href="/app/liquidaciones?tipo=salary">Salario</a>',
        'href="/app/liquidaciones?tipo=settlement">Liquidación</a>',
        'href="/app/aguinaldo">Aguinaldo</a>',
        'href="/app/calculations?tipo=notice">Preaviso</a>',
        'href="/app/vacations">Vacaciones</a>',
        'href="/app/calculation-operations?tipo=advance">Anticipo</a>',
        'href="/app/calculation-operations?tipo=discipline">Amonestaciones / Suspensión / Permisos</a>',
        'href="/app/calculation-operations?tipo=telegram">Telegrama colacionado</a>',
        'href="/app/employee-history">Histórico funcionario</a>',
        'href="/app/medical-exams">Examen Médico</a>',
    ]
    assert (block.count('class="workspace-nav-link')) == 10
    assert all(item in block for item in expected)
    for removed in (
        "Panel de Cálculo",
        "Calculadora de horas y recargos",
        "Calculadora de aguinaldo",
        "Calculadora de vacaciones",
        "Liquidaciones mensuales",
        "Cobertura de períodos",
    ):
        assert removed not in block


def test_calculation_secondary_navigation_matches_the_ten_requested_submodules():
    nav = (ROOT / "app" / "templates" / "module_subnav.html").read_text(encoding="utf-8")
    start = nav.index("tab_nav('Subsecciones de cálculo laboral', [")
    end = nav.index("]) }}", start)
    block = nav[start:end]
    expected_labels = [
        "'Salario'", "'Liquidación'", "'Aguinaldo'", "'Preaviso'",
        "'Vacaciones'", "'Anticipo'", "'Amonestaciones / Suspensión / Permisos'",
        "'Telegrama colacionado'", "'Histórico funcionario'", "'Examen Médico'",
    ]
    assert block.count("{'label':") == 10
    assert all(label in block for label in expected_labels)
    assert "'label':'Panel'" not in block
    assert "Carga de hora" not in block
    assert "Cobertura de períodos" not in block
    assert "Liquidaciones mensuales" not in block


def test_salary_entry_uses_the_professional_engine_and_surfaces_additional_earnings():
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    cards = (ROOT / "app" / "templates" / "calculations.html").read_text(encoding="utf-8")
    workbench = (ROOT / "app" / "templates" / "labor_workbench.html").read_text(encoding="utf-8")
    fields = (ROOT / "app" / "calculator_fields.py").read_text(encoding="utf-8")
    assert 'href="/app/liquidaciones?tipo=salary">Salario</a>' in _calculation_sidebar_block()
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
