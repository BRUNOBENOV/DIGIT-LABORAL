"""REOP Liquidación Salario and REI declaration have distinct, clear workflows.

The salary calculator creates/updates a saved payroll calculation. The
communications page reads those calculations, including imported MOV salary
evidence, without approving them again.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_salary_paths_do_not_confuse_calculation_with_communication():
    sidebar = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
    assert 'href="/app/liquidaciones?tipo=salary">Cálculo de salario</a>' in sidebar
    assert 'href="/app/reports/liquidaciones-salarios">Liquidaciones y recibos de salario</a>' in sidebar
    assert 'href="/app/compliance/salary-import?authority=REOP">Liquidación de salario · REOP</a>' in sidebar
    assert 'href="/app/compliance/salary-import?authority=REI">Declaración de salarios · REI</a>' in sidebar
    assert 'href="/app/calculations?tipo=salary">Salario</a>' not in sidebar


def test_reop_communication_has_one_read_only_export_workflow_not_double_approval():
    template = (ROOT / "app/templates/salary_import.html").read_text(encoding="utf-8")
    assert "Liquidación de salario · REOP" in template
    assert "Declaración de salarios · REI" in template
    assert "Verificar liquidación para REOP" in template
    assert "2. Revisión" in template
    assert "3. Presentación y comprobante oficial" in template
    assert "Opciones avanzadas de lectura" in template
    assert 'value="auto"' in template
    assert 'action="/app/compliance/salary-import/export"' in template
    assert 'action="/app/compliance/salary-import/approve-pending"' not in template
    assert 'action="/app/calculations/{{ excluded.calculation_id }}/status"' not in template
    assert "Importar datos es una operación distinta" in template


def test_central_compliance_calls_things_by_their_official_purpose():
    template = (ROOT / "app/templates/compliance.html").read_text(encoding="utf-8")
    assert "Preparar liquidación de salario · REOP" in template
    assert "Preparar declaración de salarios · REI" in template
    assert "Centro de cumplimiento · REOP y REI" in template


def test_workbench_does_not_offer_an_unrelated_extra_salary_import_action():
    template = (ROOT / "app/templates/labor_workbench.html").read_text(encoding="utf-8")
    assert "Liquidaciones y recibos guardados" in template
    assert "Preparar Liquidación de salario en REOP" in template
    assert "Validar REOP / REI" not in template
