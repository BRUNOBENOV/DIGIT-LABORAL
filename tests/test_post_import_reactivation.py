"""Regression coverage for the one-time post-import employee correction tool."""
from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import AuditLog, Company, Employee, EmployeeEvent, EmployeeExit, FinalSettlement, Studio
from app.post_import_reactivation import apply_correction, build_correction_preview, parse_correction_file


def _xlsx(rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    data = BytesIO()
    workbook.save(data)
    workbook.close()
    return data.getvalue()


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        studio = Studio(name="Studio post-import")
        db.add(studio)
        db.flush()
        company = Company(studio_id=studio.id, legal_name="Empresa importada", ruc="1234567-8", status="Activa")
        other = Company(studio_id=studio.id, legal_name="Otra empresa", ruc="9876543-2", status="Activa")
        db.add_all([company, other])
        db.flush()
        ids = (studio.id, company.id, other.id)
        db.commit()
        yield db, ids
    engine.dispose()


def _employee(db, company_id, code, *, status="Desvinculado", source_code=None, terminated=True):
    employee = Employee(
        company_id=company_id, employee_code=code,
        full_name=f"Funcionario {code}", document_number=f"CI-{company_id}-{code}",
        position="Administración", admission_date=date(2019, 3, 15),
        termination_date=date(2022, 5, 10) if terminated else None,
        status=status, base_salary=2_500_000,
        notes=f"Importación histórica: base.xlsx. Código(s) histórico(s) CODTRA: {source_code}. Filas de origen: 2."
              if source_code else "Legajo ordinario",
    )
    db.add(employee)
    db.flush()
    return employee


def test_csv_xlsx_single_column_and_381_rows():
    rows = [["employee_id"]] + [[index] for index in range(1, 382)]
    kind, parsed = parse_correction_file(_xlsx(rows), "correccion.xlsx")
    assert kind == "employee_id"
    assert len(parsed) == 381
    assert parsed[0]["identifier"] == "1"
    kind, parsed = parse_correction_file(b"CODTRA\n0001\n10003\n", "codigos.csv")
    assert kind == "codtra"
    assert [row["identifier"] for row in parsed] == ["0001", "10003"]


@pytest.mark.parametrize("content,filename", [
    (b"name\n1\n", "file.csv"),
    (b"employee_id,CODTRA\n1,10\n", "file.csv"),
    (b"employee_id\n1,10\n", "file.csv"),
    (b"", "file.csv"),
    (b"employee_id\n1\n", "file.xls"),
])
def test_reject_invalid_file_format(content, filename):
    with pytest.raises(ValueError):
        parse_correction_file(content, filename)


def test_review_classifies_duplicates_ambiguity_active_and_nonexistent(session):
    db, (_, first_company, second_company) = session
    eligible = _employee(db, first_company, 900, source_code="1234")
    _employee(db, second_company, 901, source_code="1234")
    active = _employee(db, first_company, 902, status="Activo", source_code="8765")
    db.commit()
    kind, entries = parse_correction_file(b"CODTRA\n1234\n8765\n9999\n8765\n", "list.csv")
    preview = build_correction_preview(db, kind=kind, entries=entries, allowed_company_ids={first_company, second_company})
    assert preview["summary"] == {"detected": 4, "ready": 0, "excluded": 4}
    assert "ambiguo" in preview["rows"][0]["reason"]
    assert "Activo" in preview["rows"][1]["reason"]
    assert "No se encontr" in preview["rows"][2]["reason"]
    assert "repetido" in preview["rows"][3]["reason"]
    assert eligible.status == "Desvinculado" and active.status == "Activo"


def test_correction_preserves_admission_and_audits_each_employee(session):
    db, (studio_id, company_id, _) = session
    first = _employee(db, company_id, 705, source_code="11")
    second = _employee(db, company_id, 706, source_code="12", terminated=False)
    already_active = _employee(db, company_id, 707, status="Activo")
    db.commit()
    content = f"employee_id\n{first.id}\n{second.id}\n{already_active.id}\n".encode()
    kind, entries = parse_correction_file(content, "ids.csv")
    preview = build_correction_preview(db, kind=kind, entries=entries, allowed_company_ids={company_id})
    assert preview["summary"]["ready"] == 2
    assert preview["summary"]["excluded"] == 1

    result = apply_correction(
        db, preview=preview, allowed_company_ids={company_id},
        studio_id=studio_id, user_email="admin@example.test",
    )
    assert result == 2
    db.commit()
    db.refresh(first)
    db.refresh(second)
    assert first.status == second.status == "Activo"
    assert first.termination_date is None and second.termination_date is None
    assert first.admission_date == second.admission_date == date(2019, 3, 15)
    assert first.base_salary == second.base_salary == 2_500_000
    assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.entity_id.in_([str(first.id), str(second.id)]))) == 2
    assert db.scalar(select(func.count(EmployeeEvent.id)).where(EmployeeEvent.employee_id.in_([first.id, second.id]))) == 2

    with pytest.raises(ValueError, match="cambiaron"):
        apply_correction(
            db, preview=preview, allowed_company_ids={company_id},
            studio_id=studio_id, user_email="admin@example.test",
        )


def test_stale_preview_is_all_or_nothing(session):
    db, (studio_id, company_id, _) = session
    first = _employee(db, company_id, 110, source_code="110")
    second = _employee(db, company_id, 111, source_code="111")
    db.commit()
    kind, entries = parse_correction_file(f"employee_id\n{first.id}\n{second.id}\n".encode(), "ids.csv")
    preview = build_correction_preview(db, kind=kind, entries=entries, allowed_company_ids={company_id})
    second.status = "Activo"
    db.commit()
    with pytest.raises(ValueError):
        apply_correction(db, preview=preview, allowed_company_ids={company_id}, studio_id=studio_id, user_email="admin@test.local")
    db.rollback()
    db.refresh(first)
    assert first.status == "Desvinculado"
    assert first.termination_date == date(2022, 5, 10)
    assert db.scalar(select(func.count(AuditLog.id))) == 0


def test_settlement_and_non_cancelled_exit_excluded(session):
    db, (_, company_id, _) = session
    first = _employee(db, company_id, 200, source_code="200")
    second = _employee(db, company_id, 201, source_code="201")
    db.flush()
    first_exit = EmployeeExit(company_id=company_id, employee_id=first.id, effective_date=date(2022, 5, 10),
                              reason="Renuncia", initiated_by="Trabajador", status="Cancelado")
    second_exit = EmployeeExit(company_id=company_id, employee_id=second.id, effective_date=date(2022, 5, 10),
                               reason="Renuncia", initiated_by="Trabajador", status="Efectivo")
    db.add_all([first_exit, second_exit])
    db.flush()
    db.add(FinalSettlement(company_id=company_id, employee_id=first.id, employee_exit_id=first_exit.id))
    db.commit()
    kind, entries = parse_correction_file(f"employee_id\n{first.id}\n{second.id}\n".encode(), "ids.csv")
    preview = build_correction_preview(db, kind=kind, entries=entries, allowed_company_ids={company_id})
    assert "liquidación final" in preview["rows"][0]["reason"]
    assert "egreso formal" in preview["rows"][1]["reason"]
    assert preview["summary"]["ready"] == 0
