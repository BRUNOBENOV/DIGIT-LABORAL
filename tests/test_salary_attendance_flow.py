"""Asistencia trazable desde el cálculo hasta Liquidación y el archivo oficial."""
import io
import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from openpyxl import load_workbook
from sqlalchemy import select

from app.approved_salary_import import approved_salary_records, salary_excluded_records, salary_source_summary, choose_salary_source
from app.models import CalculationRecord, SalaryImportDetail, Payroll, PayrollLine, Employee
from app.official_salary_import import prepare_import, build_reop_xlsx
from app.salary_data import approved_salary, calculation_fingerprint, select_salary_versions
from tests.test_labor_suite import web_case, token, salary


@pytest.fixture
def attendance_case(web_case):
    client, db, box, company, employee, other = web_case
    employee.admission_date = date(2024, 1, 1)
    employee.ips_contributor = True
    employee.employee_code = 207001
    employee.full_name = "PEREZ GOMEZ JUAN LUIS"
    company.mtess_employer_number = "123456"
    company.ips_employer_number = "654321"
    db.commit()
    response = client.post("/app/calculations", data={
        "csrf_token": token(client), "calculation_type": "salary",
        "company_id": company.id, "employee_id": employee.id,
        "reference_period": "2026-10", "gross": "3500000", "ips_base": "3500000", "apply_ips": "on",
        "days_worked": "22", "hours_worked": "176.5", "payment_method": "Transferencia",
    }, follow_redirects=False)
    assert response.status_code == 303
    item = db.scalar(select(CalculationRecord).order_by(CalculationRecord.id.desc()))
    assert client.post(f"/app/calculations/{item.id}/status", data={"csrf_token": token(client), "status": "Aprobado"}, follow_redirects=False).status_code == 303
    db.expire_all()
    return client, db, box, company, employee, other, item


def proposal(case):
    client, _, _, company, employee, *_ = case
    response = client.get("/api/liquidaciones/asistencia-salarial", params={"company_id":company.id,"employee_id":employee.id,"period":"2026-10"})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    return response.json()


def linked_form(case, **updates):
    client, _, _, company, employee, *_ = case
    origin = proposal(case)
    return {**salary(), "csrf_token":token(client), "company_id":str(company.id), "employee_id":str(employee.id),
            "month":"2026-10", "attendance_source_id":str(origin["calculation_id"]),
            "attendance_source_sha256":origin["fingerprint"], **origin["values"], **updates}


def test_approved_salary_prefills_liquidation_with_readonly_attendance(attendance_case):
    client, _, _, company, employee, _, source = attendance_case
    response = client.get("/app/liquidaciones", params={"tipo":"salary","company_id":company.id,"employee_id":employee.id,"month":"2026-10"})
    assert response.status_code == 200
    form = BeautifulSoup(response.text,"html.parser").select_one("#labor-form")
    for name, value in (("days_worked","22"),("hours_worked","176.5"),("payment_method","Transferencia")):
        assert form.select_one(f'[name="{name}"]')["value"] == value
        assert form.select_one(f'[name="{name}"]').has_attr("readonly")
    assert form.select_one('[name="attendance_source_id"]')["value"] == str(source.id)
    assert form.select_one('[name="attendance_override"]')
    assert proposal(attendance_case)["values"]["hours_worked"] == "176.5"


@pytest.mark.parametrize("manual", [False, True])
def test_liquidation_inherits_or_explicitly_overrides_without_mutating_original(attendance_case, manual):
    client, db, _, company, employee, _, source = attendance_case
    original = source.input_json, source.result_json
    data = linked_form(attendance_case, days_worked="21", hours_worked="160", attendance_override="on" if manual else "")
    response = client.post("/app/liquidaciones/guardar", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text[:300]
    db.expire_all()
    draft = db.scalar(select(CalculationRecord).where(CalculationRecord.calculation_type == "suite_salary"))
    saved = json.loads(draft.input_json)
    assert saved["days_worked"] == ("21" if manual else "22")
    assert Decimal(saved["hours_worked"]) == Decimal("160" if manual else "176.5")
    assert saved["attendance_source_id"] == str(source.id)
    assert (source.input_json, source.result_json) == original
    assert approved_salary(db, company.id, employee.id, "2026-10").id == source.id
    rows, errors = prepare_import(db, company, "2026-10", "REOP", source_type="approved", payment_code="1")
    assert not errors and len(rows) == 1 and rows[0][5] == 22 and rows[0][7] == Decimal("176.5")
    workbook = load_workbook(io.BytesIO(build_reop_xlsx(rows)))
    assert workbook.active.cell(2,6).value == 22 and workbook.active.cell(2,8).value == 176.5


def test_new_approved_liquidation_replaces_original_only_after_approval(attendance_case):
    client, db, _, company, employee, _, source = attendance_case
    data = linked_form(attendance_case, days_worked="21", hours_worked="160", attendance_override="on")
    assert client.post("/app/liquidaciones/guardar", data=data, follow_redirects=False).status_code == 303
    draft = db.scalar(select(CalculationRecord).where(CalculationRecord.calculation_type == "suite_salary"))
    response = client.post(f"/app/calculations/{draft.id}/status", data={"csrf_token":token(client),"status":"Aprobado"}, follow_redirects=False)
    assert response.status_code == 303, response.text
    db.expire_all()
    assert approved_salary(db,company.id,employee.id,"2026-10").id == draft.id
    rows, errors = prepare_import(db, company, "2026-10", "REOP", source_type="approved", payment_code="1")
    assert not errors and len(rows) == 1 and rows[0][5] == 21 and rows[0][7] == Decimal("160")


def test_changed_source_or_annulment_rejects_stale_inheritance(attendance_case):
    client, db, _, company, employee, _, source = attendance_case
    data = linked_form(attendance_case)
    source.status = "Anulado"
    db.commit()
    assert not proposal(attendance_case)["available"]
    response = client.post("/app/liquidaciones/guardar",data=data)
    assert "El cálculo de origen o su asistencia cambió" in response.text
    assert db.scalar(select(CalculationRecord.id).where(CalculationRecord.calculation_type == "suite_salary")) is None
    assert salary_excluded_records(db,company.id,"2026-10")[0]["status"] == "Anulado"


def test_attendance_scope_month_and_origin_are_validated(attendance_case):
    client, db, _, company, employee, other, source = attendance_case
    assert client.get("/api/liquidaciones/asistencia-salarial",params={"company_id":company.id,"employee_id":other.id,"period":"2026-10"}).status_code == 404
    assert client.get("/api/liquidaciones/asistencia-salarial",params={"company_id":other.company_id,"employee_id":other.id,"period":"2026-10"}).status_code == 404
    assert client.get("/api/liquidaciones/asistencia-salarial",params={"company_id":company.id,"employee_id":employee.id,"period":"2026-13"}).status_code == 422
    response = client.get("/app/liquidaciones",params={"tipo":"salary","company_id":company.id,"employee_id":employee.id,"month":"2026-09","calculation_id":source.id})
    assert response.status_code == 409
    response = client.get("/app/liquidaciones",params={"tipo":"salary","company_id":company.id,"employee_id":other.id,"calculation_id":source.id})
    assert response.status_code == 404
    other_month = client.get("/api/liquidaciones/asistencia-salarial",params={"company_id":company.id,"employee_id":employee.id,"period":"2026-09"}).json()
    assert not other_month["available"] and other_month["values"] == {}


def test_attendance_lookup_rejects_roles_outside_the_calculation_module(attendance_case):
    client,db,box,company,employee,_,source=attendance_case
    box["user"].role="empresa";box["user"].company_id=company.id;db.commit()
    assert client.get("/api/liquidaciones/asistencia-salarial",params={"company_id":company.id,"employee_id":employee.id,"period":"2026-10"}).status_code==403
    assert client.get("/app/liquidaciones",params={"tipo":"salary","company_id":company.id,"employee_id":employee.id,"calculation_id":source.id}).status_code==403


def test_reviewed_attendance_changes_invalidate_an_open_inherited_form(attendance_case):
    client,db,_,company,employee,_,source=attendance_case
    data=linked_form(attendance_case)
    db.add(SalaryImportDetail(company_id=company.id,calculation_record_id=source.id,
        source_sha256=calculation_fingerprint(source),period_start=date(2026,10,1),period_end=date(2026,10,31),
        days_worked=21,hours_worked=Decimal("168"),payment_method="Transferencia"))
    db.commit()
    response=client.post("/app/liquidaciones/guardar",data=data)
    assert "El cálculo de origen o su asistencia cambió" in response.text
    assert db.scalar(select(CalculationRecord.id).where(CalculationRecord.calculation_type=="suite_salary")) is None


@pytest.mark.parametrize("hours", ["-1", "745", "NaN", "Infinity"])
def test_actual_hours_are_validated_by_the_engine(hours):
    from app.labor_calculator import calculate,CalculationError
    with pytest.raises(CalculationError):calculate(salary(hours_worked=hours))


@pytest.mark.parametrize("key,value", [("days_worked",True),("days_worked",22.5),("days_worked","NaN"),("hours_worked","incorrecto"),("hours_worked","NaN")])
def test_invalid_historical_attendance_blocks_export_without_truncation_or_server_error(attendance_case,key,value):
    _,db,_,company,_,_,source=attendance_case
    inputs=json.loads(source.input_json);inputs[key]=value;source.input_json=json.dumps(inputs);db.commit()
    _,errors=prepare_import(db,company,"2026-10","REOP",source_type="approved",payment_code="1")
    assert errors
    assert any(("jornadas" if key=="days_worked" else "horas") in error for error in errors)


@pytest.mark.parametrize("key,value",[("days_worked",True),("hours_worked","incorrecto")])
def test_explicit_review_can_correct_invalid_historical_attendance_in_an_annex(attendance_case,key,value):
    client,db,_,_,_,_,source=attendance_case
    inputs=json.loads(source.input_json);inputs[key]=value;source.input_json=json.dumps(inputs);db.commit()
    response=client.post("/app/compliance/salary-import/details",data={"csrf_token":token(client),"calculation_id":source.id,
        "authority":"REOP","period_start":"2026-10-01","period_end":"2026-10-31","days_worked":"22","hours_worked":"176.5",
        "payment_method":"Transferencia","confirmed":"si","override_existing":"on"},follow_redirects=False)
    assert response.status_code==303
    assert proposal(attendance_case)["values"]["days_worked"]=="22"
    assert proposal(attendance_case)["values"]["hours_worked"]=="176.50"


def test_rei_annex_preserves_existing_reop_hours_and_requires_explicit_overwrite(attendance_case):
    client, db, _, _, _, _, source = attendance_case
    data={"csrf_token":token(client),"calculation_id":source.id,"authority":"REI","period_start":"2026-10-01","period_end":"2026-10-31","days_worked":"22","confirmed":"si"}
    assert client.post("/app/compliance/salary-import/details",data=data,follow_redirects=False).status_code == 303
    detail=db.scalar(select(SalaryImportDetail).where(SalaryImportDetail.calculation_record_id==source.id))
    assert detail.hours_worked == Decimal("176.5") and detail.payment_method == "Transferencia"
    assert client.post("/app/compliance/salary-import/details",data=dict(data,days_worked="21")).status_code == 409
    assert client.post("/app/compliance/salary-import/details",data=dict(data,days_worked="21",override_existing="on"),follow_redirects=False).status_code == 303
    assert proposal(attendance_case)["values"]["days_worked"] == "21"
    assert proposal(attendance_case)["origins"]["days_worked"] == "Anexo de asistencia revisado"


def test_preview_shows_attendance_and_actual_employee_codes(attendance_case):
    client, db, _, company, employee, _, source = attendance_case
    params={"company_id":company.id,"period":"2026-10","source_type":"approved","authority":"REOP","payment_code":"1"}
    html=client.get("/app/compliance/salary-import",params=params).text
    soup=BeautifulSoup(html,"html.parser")
    assert "Horas ordinarias" in soup.get_text() and "Jornadas" in soup.get_text()
    assert any("176.5" in cell.get_text() for cell in soup.select("td"))
    source.status="Anulado";db.commit()
    html=client.get("/app/compliance/salary-import",params=params).text
    assert "Legajo 207001" in html and "PEREZ GOMEZ JUAN LUIS" in html


@pytest.mark.parametrize("barrier", ["Anulado", "Estado desconocido"])
def test_drafts_never_cross_an_annulment_or_unknown_status(barrier):
    def record(id_,status):return SimpleNamespace(id=id_,employee_id=7,status=status)
    selected=select_salary_versions([record(4,"Borrador"),record(3,barrier),record(2,"Aprobado")])
    assert selected[7].status == barrier


def test_explicit_employee_auto_source_keeps_approval_when_payroll_exists(attendance_case):
    _,db,_,company,employee,_,_=attendance_case
    db.add(Payroll(company_id=company.id,period="2026-10",status="Cerrada",closed_at=datetime(2026,10,31)))
    db.commit()
    assert choose_salary_source(db,company.id,"2026-10","auto",employee_id=employee.id) == "approved"
    assert choose_salary_source(db,company.id,"2026-10","auto") == "payroll"
    payroll=db.scalar(select(Payroll).where(Payroll.company_id==company.id))
    db.add(PayrollLine(payroll_id=payroll.id,employee_id=employee.id))
    db.commit()
    assert choose_salary_source(db,company.id,"2026-10","auto") == "approved"
    worker=Employee(company_id=company.id,full_name="Otra persona de prueba",document_number="2000003")
    db.add(worker);db.flush()
    db.add(PayrollLine(payroll_id=payroll.id,employee_id=worker.id));db.commit()
    assert choose_salary_source(db,company.id,"2026-10","auto") == "payroll"


def test_preview_distinguishes_two_exclusions_from_one_included_worker(attendance_case):
    client,db,_,company,_,_,_=attendance_case
    for code in (300002,300003):
        employee=Employee(company_id=company.id,employee_code=code,full_name=f"Persona sintética {code}",document_number=str(code),admission_date=date(2024,1,1))
        db.add(employee);db.flush()
        db.add(CalculationRecord(company_id=company.id,employee_id=employee.id,calculation_type="salary",reference_period="2026-10",status="Borrador"))
    db.commit()
    html=client.get("/app/compliance/salary-import",params={"company_id":company.id,"period":"2026-10","source_type":"approved","payment_code":"1"}).text
    soup=BeautifulSoup(html,"html.parser")
    text=soup.get_text(" ",strip=True)
    assert "2 sin aprobación" in text
    assert "1 trabajador(es) para REOP" in text
    assert "Legajo 300002" in text and "Legajo 300003" in text


def test_changed_attendance_blocks_first_approval_of_an_inherited_draft(attendance_case):
    client,db,_,company,_,_,source=attendance_case
    assert client.post("/app/liquidaciones/guardar",data=linked_form(attendance_case),follow_redirects=False).status_code==303
    draft=db.scalar(select(CalculationRecord).where(CalculationRecord.calculation_type=="suite_salary"))
    db.add(SalaryImportDetail(company_id=company.id,calculation_record_id=source.id,source_sha256=calculation_fingerprint(source),
        period_start=date(2026,10,1),period_end=date(2026,10,31),days_worked=21,hours_worked=Decimal("168"),payment_method="Transferencia"))
    db.commit()
    response=client.post(f"/app/calculations/{draft.id}/status",data={"csrf_token":token(client),"status":"Aprobado"})
    assert response.status_code==409
    db.expire_all()
    assert draft.status=="Borrador"


def test_saved_salary_exposes_review_and_returns_to_the_document_after_approval(attendance_case):
    client,db,box,_,_,_,_=attendance_case
    response=client.post("/app/liquidaciones/guardar",data=linked_form(attendance_case),follow_redirects=False)
    assert response.status_code==303
    location=response.headers["location"]
    soup=BeautifulSoup(client.get(location).text,"html.parser")
    button=soup.select_one('button[name="status"][value="Aprobado"]')
    assert button and "Aprobar salario revisado" in button.get_text()
    action=button.find_parent("form")["action"]
    box["user"].role="auxiliar";db.commit()
    assert 'value="Aprobado"' not in client.get(location).text
    box["user"].role="contador";db.commit()
    approved=client.post(action,data={"csrf_token":token(client),"status":"Aprobado"},follow_redirects=False)
    assert approved.status_code==303 and approved.headers["location"]==location
    html=client.get(location).text
    assert "Exportar REOP / REI" in html


@pytest.mark.parametrize("authority", ["REOP", "REI"])
def test_ips_no_never_appears_in_export_selector_preview_or_partials(attendance_case, authority):
    client, db, _, company, employee, _, item = attendance_case
    worker = Employee(
        company_id=company.id, employee_code=900021, full_name="TRABAJADOR SIN IPS",
        document_number="9000021", ips_contributor=False,
        admission_date=date(2024, 1, 1), status="Activo",
    )
    db.add(worker)
    db.flush()
    for status in ("Aprobado", "Borrador"):
        db.add(CalculationRecord(
            company_id=company.id, employee_id=worker.id, calculation_type="salary",
            reference_period="2026-10", source="Calculadora v2.4", status=status,
            input_json=item.input_json, result_json=item.result_json, amount=item.amount,
        ))
    db.commit()
    params = {
        "company_id": company.id, "period": "2026-10",
        "authority": authority, "source_type": "approved",
        "payment_code": "1", "name_order": "apellido_primero", "rei_category": "E",
    }
    page = client.get("/app/compliance/salary-import", params=params)
    assert page.status_code == 200
    soup = BeautifulSoup(page.text, "html.parser")
    assert "TRABAJADOR SIN IPS" not in soup.get_text(" ", strip=True)
    assert "TRABAJADOR SIN IPS" not in str(soup.select_one('[name="employee_id"]'))
    assert "1 trabajador(es)" in soup.get_text(" ", strip=True)
    assert not salary_excluded_records(db, company.id, "2026-10", authority=authority)
    summary = salary_source_summary(db, company.id, "2026-10", authority=authority)
    assert summary["approved"] == 1 and summary["pending"] == 0
    assert client.get("/app/compliance/salary-import",
                      params={**params, "employee_id": worker.id}).status_code == 422
    assert client.post("/app/compliance/salary-import/export", data={
        **params, "employee_id": str(worker.id),
        "csrf_token": token(client), "confirmed": "si",
    }).status_code == 422


def test_reop_payroll_selector_excludes_ips_no(attendance_case):
    client, db, _, company, employee, _, _ = attendance_case
    no_ips = Employee(
        company_id=company.id, employee_code=900022, full_name="PAGO SIN IPS",
        document_number="9000022", ips_contributor=False,
        admission_date=date(2024, 1, 1),
    )
    db.add(no_ips)
    db.flush()
    payroll = Payroll(company_id=company.id, period="2026-10",
                      status="Cerrada", closed_at=datetime(2026, 10, 31))
    db.add(payroll)
    db.flush()
    db.add_all([
        PayrollLine(payroll_id=payroll.id, employee_id=employee.id),
        PayrollLine(payroll_id=payroll.id, employee_id=no_ips.id),
    ])
    db.commit()
    response = client.get("/app/compliance/salary-import", params={
        "company_id": company.id, "period": "2026-10",
        "authority": "REOP", "source_type": "payroll", "payment_code": "1",
    })
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    selector = soup.select_one('[name="employee_id"]')
    assert selector is not None
    assert "PAGO SIN IPS" not in selector.get_text(" ", strip=True)
    assert "PEREZ GOMEZ JUAN LUIS" in selector.get_text(" ", strip=True)


def test_reop_rei_async_employee_selector_filters_ips_yes_at_api_level(attendance_case):
    from pathlib import Path
    client, db, _, company, employee, _, _ = attendance_case
    excluded = Employee(
        company_id=company.id, employee_code=900025, full_name="EXCLUIDO IPS NO",
        document_number="9000025", ips_contributor=False,
        admission_date=date(2024, 1, 1), status="Activo",
    )
    db.add(excluded)
    db.commit()
    endpoint = "/api/selectors/employees"
    params = {"company_id": company.id, "ips_only": "true"}
    results = client.get(endpoint, params={**params, "q": "EXCLUIDO IPS NO"})
    assert results.status_code == 200 and results.json()["items"] == []
    assert client.get(endpoint, params={
        **params, "selected_id": excluded.id,
    }).status_code == 404
    kept = client.get(endpoint, params={**params, "selected_id": employee.id})
    assert kept.status_code == 200 and kept.json()["items"][0]["id"] == employee.id

    employee.status = "Desvinculado"
    db.commit()
    assert client.get(endpoint, params={
        **params, "active_only": "true", "selected_id": employee.id,
    }).status_code == 404
    assert client.get(endpoint, params={
        **params, "selected_id": employee.id,
    }).status_code == 200  # REOP conserva los IPS Sí desvinculados.

    script = (Path(__file__).resolve().parents[1] / "app/static/entity-selects.js").read_text("utf-8")
    assert 'url.searchParams.set("ips_only", "true")' in script
    assert 'url.searchParams.set("active_only", "true")' in script
