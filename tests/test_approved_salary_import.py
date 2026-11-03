"""Regresión: cálculo aprobado visible sin nómina y sin perder validaciones."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from app import approved_salary_import as source
from app import official_salary_import as exporter
from app.models import CalculationRecord, Employee, IntegrationBatch, Payroll, SalaryImportDetail


class FakeSession:
    def __init__(self, records, employee, supplement=None, payroll=None):
        self.records = records
        self.employee = employee
        self.supplement = supplement
        self.payroll = payroll

    def scalar(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        if entity is Payroll:
            return self.payroll
        return None

    def scalars(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        if entity is CalculationRecord:
            return self.records
        if entity is Employee:
            return [self.employee]
        if entity is IntegrationBatch:
            return []
        if entity is SalaryImportDetail:
            return [self.supplement] if self.supplement else []
        raise AssertionError(f"Unexpected query: {entity}")


def case():
    item = SimpleNamespace(
        id=50, company_id=7, employee_id=8, reference_period="2026-10",
        calculation_type="salary", source="Cálculo automático", status="Aprobado",
        input_json=json.dumps({
            "gross": 3000000, "other_income": 0, "other_discount": 0,
            "apply_ips": True, "reference_period": "2026-10",
        }),
        result_json=json.dumps({
            "gross_computable": 3000000, "ips_base": 3000000,
            "ips_rate": 9, "ips_employee": 270000, "discounts": 270000, "net": 2730000,
        }),
        amount=2730000,
        created_at=datetime(2026, 10, 28, 13),
    )
    employee = SimpleNamespace(
        id=8, company_id=7, branch_id=None, employee_code=8,
        full_name="PEREZ GOMEZ JUAN LUIS", document_number="1234567",
        admission_date=date(2024, 1, 1), termination_date=None,
        ips_contributor=True, status="Activo", payment_frequency="Mensual",
    )
    company = SimpleNamespace(id=7, ruc="80000000-1",
                              ips_employer_number="654321", mtess_employer_number="123456")
    detail = SimpleNamespace(
        company_id=7, calculation_record_id=50, source_sha256=source.calculation_fingerprint(item),
        period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
        days_worked=22, hours_worked=Decimal("176"),
        payment_method="Transferencia",
    )
    return item, employee, company, detail


def test_approved_saved_calculation_replaces_missing_payroll_error():
    item, employee, company, detail = case()
    db = FakeSession([item], employee, detail)
    summary = source.salary_source_summary(db, company.id, "2026-10")
    assert summary["approved"] == 1 and not summary["closed_payroll"]
    assert source.choose_salary_source(db, company.id, "2026-10", "auto") == "approved"
    rows, errors = exporter.prepare_import(db, company, "2026-10", "REOP",
                                           source_type="auto", payment_code="1")
    assert errors == []
    assert len(rows) == 1 and len(rows[0]) == 32
    assert rows[0][9] == 3000000
    assert rows[0][5] == 22 and rows[0][7] == 176
    assert rows[0][25] == 270000


def test_missing_hours_are_blocking_not_invented_from_divisor():
    item, employee, company, _detail = case()
    db = FakeSession([item], employee)
    rows, errors = exporter.prepare_import(db, company, "2026-10", "REOP",
                                           source_type="approved", payment_code="1")
    assert len(rows) == 1
    assert any("faltan horas ordinarias" in error for error in errors)
    assert any("falta registrar jornadas trabajadas reales" in error for error in errors)


def test_newer_draft_preserves_current_approval_until_review():
    item, employee, company, detail = case()
    more_recent = SimpleNamespace(**vars(item))
    more_recent.id = 51
    more_recent.status = "Revisar"
    more_recent.created_at = datetime(2026, 10, 30, 10)
    db = FakeSession([more_recent, item], employee, detail)
    rows, errors = exporter.prepare_import(db, company, "2026-10", "REOP",
                                           source_type="approved", payment_code="1")
    assert len(rows) == 1 and not errors
    assert not source.salary_excluded_records(db, company.id, "2026-10")
    selected, selected_errors, details = source.approved_salary_records(
        db, company, "2026-10", employee_id=employee.id,
    )
    assert len(selected) == 1 and not selected_errors and details[0]["id"] == item.id
    assert source.salary_source_summary(db, company.id, "2026-10")["drafts_in_progress"] == 1


def test_stale_supplement_is_not_applied_when_calculation_changes():
    item, employee, company, detail = case()
    detail.source_sha256 = "0" * 64
    db = FakeSession([item], employee, detail)
    _, errors = exporter.prepare_import(db, company, "2026-10", "REOP",
                                        source_type="approved", payment_code="1")
    assert any("faltan horas ordinarias" in error for error in errors)


def test_rei_uses_preserved_ips_base_from_approved_calculation():
    item, employee, company, detail = case()
    db = FakeSession([item], employee, detail)
    rows, errors = exporter.prepare_import(db, company, "2026-10", "REI",
                                           source_type="approved", name_order="apellido_primero",
                                           rei_category="E")
    assert errors == []
    assert rows[0][7] == 3000000
    assert rows[0][3] == "PEREZ GOMEZ"
    assert rows[0][4] == "JUAN LUIS"



def test_rei_only_requires_days_not_reop_hours_or_payment():
    item, employee, company, detail = case()
    detail.hours_worked = Decimal("0")
    detail.payment_method = ""
    db = FakeSession([item], employee, detail)
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REI", name_order="apellido_primero",
        rei_category="E", source_type="approved", employee_id=employee.id,
    )
    assert errors == []
    assert len(rows) == 1
    assert rows[0][6] == 22
    assert rows[0][7] == 3000000
    reop_rows, reop_errors = exporter.prepare_import(
        db, company, "2026-10", "REOP", payment_code="1",
        source_type="approved", employee_id=employee.id,
    )
    assert len(reop_rows) == 1
    assert any("horas ordinarias" in e for e in reop_errors)
    assert any("forma de pago" in e for e in reop_errors)


def test_legacy_salary_ips_rate_comes_from_approved_inputs():
    item, employee, company, detail = case()
    saved = json.loads(item.result_json)
    saved.pop("ips_rate")
    item.result_json = json.dumps(saved)
    input_data = json.loads(item.input_json)
    input_data["ips_rate"] = 9.0
    item.input_json = json.dumps(input_data)
    detail.source_sha256 = source.calculation_fingerprint(item)
    db = FakeSession([item], employee, detail)
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP", payment_code="1",
        source_type="approved", employee_id=employee.id,
    )
    assert errors == []
    assert rows[0][25] == 270000


def test_ips_opt_out_is_not_reinterpreted_as_deduction():
    item, employee, company, detail = case()
    inputs = json.loads(item.input_json)
    inputs.update({"ips_rate": 9, "apply_ips": False})
    item.input_json = json.dumps(inputs)
    result = json.loads(item.result_json)
    result["ips_employee"] = result["discounts"] = 0
    result["net"] = result["gross_computable"]
    result.pop("ips_rate")
    item.result_json = json.dumps(result)
    item.amount = result["net"]
    detail.source_sha256 = source.calculation_fingerprint(item)
    db = FakeSession([item], employee, detail)
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP", payment_code="1", source_type="approved",
        employee_id=employee.id,
    )
    assert errors == []
    assert rows[0][25] == 0


def test_explicit_employee_scope_is_present_in_approval_query():
    item, employee, company, detail = case()

    class RecordingSession(FakeSession):
        def __init__(self):
            super().__init__([item], employee, detail)
            self.statements = []
        def scalars(self, stmt):
            self.statements.append(str(stmt))
            return super().scalars(stmt)

    db = RecordingSession()
    _source, errors, details = source.approved_salary_records(
        db, company, "2026-10", employee_id=employee.id,
    )
    assert not errors and len(details) == 1
    assert any("calculation_records.employee_id =" in q for q in db.statements)



def test_a_company_export_with_one_draft_and_one_approved_keeps_eligible_snapshot():
    item, employee, company, detail = case()
    draft = SimpleNamespace(**vars(item))
    draft.id = 77
    draft.employee_id = 777
    draft.status = "Borrador"
    draft.created_at = datetime(2026, 10, 31)
    db = FakeSession([draft, item], employee, detail)
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP",
        source_type="approved", payment_code="1",
    )
    assert not errors
    assert len(rows) == 1 and rows[0][9] == 3000000
    exclusions = source.salary_excluded_records(db, company.id, "2026-10")
    assert len(exclusions) == 1
    assert exclusions[0]["employee_id"] == 777
    assert exclusions[0]["status"] == "Borrador"


def test_approved_source_reports_missing_days_and_hours_only_once():
    item, employee, company, detail = case()
    db = FakeSession([item], employee)
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REOP",
        source_type="approved", employee_id=employee.id, payment_code="1",
    )
    assert len(rows) == 1
    assert len([e for e in errors if "jornada" in e or "días trabajad" in e]) == 1
    assert len([e for e in errors if "horas ordinarias" in e]) == 1


def test_latest_approved_employee_choices_exclude_drafts():
    item, employee, company, detail = case()
    draft = SimpleNamespace(**vars(item))
    draft.id = 78
    draft.employee_id = 777
    draft.status = "Borrador"
    draft.created_at = datetime(2026, 11, 1)
    db = FakeSession([draft, item], employee, detail)
    options = source.approved_employee_choices(db, company.id, "2026-10")
    assert [e.id for e in options] == [employee.id]


def test_rei_approved_source_includes_only_active_ips_yes_saved_salary():
    item, employee, company, detail = case()
    no_ips = SimpleNamespace(**vars(employee))
    no_ips.id, no_ips.employee_code, no_ips.ips_contributor = 9, 9, False
    no_ips.document_number = "2222222"
    inactive = SimpleNamespace(**vars(employee))
    inactive.id, inactive.employee_code, inactive.status = 10, 10, "Desvinculado"
    inactive.document_number = "3333333"
    archived = SimpleNamespace(**vars(employee))
    archived.id, archived.employee_code, archived.status = 11, 11, "Archivado"
    archived.document_number = "4444444"
    workers = [employee, no_ips, inactive, archived]
    calculations = [item]
    for worker in workers[1:]:
        copy = SimpleNamespace(**vars(item))
        copy.id = 50 + worker.id
        copy.employee_id = worker.id
        calculations.append(copy)

    class MultiSession(FakeSession):
        def scalars(self, stmt):
            entity = stmt.column_descriptions[0]["entity"]
            if entity is Employee:
                return workers
            if entity is CalculationRecord:
                return calculations
            return super().scalars(stmt)

    db = MultiSession(calculations, employee, detail)
    rows, errors = exporter.prepare_import(
        db, company, "2026-10", "REI", source_type="approved",
        name_order="apellido_primero", rei_category="E",
    )
    assert errors == []
    assert len(rows) == 1
    assert rows[0][2] == employee.document_number
    assert rows[0][7] == 3000000
    # Al contrario, REOP no usa el filtro de afiliación/estado de REI.
    reop_rows, _reop_errors, _reop_diagnostics = source.approved_salary_records(
        db, company, "2026-10", authority="REOP",
    )
    assert len(reop_rows) == 4


def test_rei_draft_warning_ignores_non_ips_and_inactive_workers():
    item, employee, company, detail = case()
    draft = SimpleNamespace(**vars(item))
    draft.id, draft.employee_id, draft.status = 77, 77, "Borrador"
    no_ips = SimpleNamespace(**vars(employee))
    no_ips.id, no_ips.ips_contributor = 77, False

    class MultiSession(FakeSession):
        def scalars(self, stmt):
            entity = stmt.column_descriptions[0]["entity"]
            if entity is Employee:
                return [employee, no_ips]
            if entity is CalculationRecord:
                return [draft, item]
            return super().scalars(stmt)

    db = MultiSession([draft, item], employee, detail)
    assert not source.salary_excluded_records(db, company.id, "2026-10", authority="REI")
    excluded_reop = source.salary_excluded_records(db, company.id, "2026-10")
    assert len(excluded_reop) == 1 and excluded_reop[0]["employee_id"] == 77
    choices = source.approved_employee_choices(db, company.id, "2026-10", authority="REI")
    assert [person.id for person in choices] == [employee.id]
