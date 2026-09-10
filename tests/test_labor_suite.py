from __future__ import annotations

import importlib.util
import io
import re
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.labor_calculator import CalculationError, calculate, notice_days, vacation_days, anniversary
from app.liquidation_export import build_liquidation_pdf, build_liquidation_csv


def salary(**changes):
    data = dict(kind="salary", salary="3500000", days_paid="30", days_worked="22",
                month="2026-09", issued_date="2026-09-09", apply_ips="on",
                ips_rate="9", employer_rate="16.5", two_copies="on",
                employer="Empresa de ejemplo", ruc="80000000-0",
                employee="Trabajador de ejemplo", ci="1000000")
    return dict(data, **changes)


def settlement(**changes):
    return dict(kind="settlement", salary="3000000", days_paid="0",
        start_date="2024-01-01", end_date="2026-07-01", issued_date="2026-09-09",
        reason="dismissal", indefinite="on", trial_completed="on",
        average_salary="3000000", annual_remuneration="18000000", **changes)


@pytest.mark.parametrize("end,expected", [
    (date(2021,1,1),30), (date(2021,1,2),45), (date(2025,1,1),45),
    (date(2025,1,2),60), (date(2030,1,1),60), (date(2030,1,2),90)])
def test_notice_exact_anniversaries(end, expected):
    assert notice_days(date(2020,1,1),end) == expected


@pytest.mark.parametrize("end,expected", [
    (date(2020,12,31),0), (date(2021,1,1),12), (date(2025,1,1),12),
    (date(2025,1,2),18), (date(2030,1,1),18), (date(2030,1,2),30)])
def test_vacation_exact_anniversaries(end, expected):
    assert vacation_days(date(2020,1,1),end) == expected


def test_calendar_leap_day():
    assert anniversary(date(2020,2,29),1) == date(2021,2,28)
    assert notice_days(date(2020,2,29),date(2021,3,1)) == 45


def test_salary_and_employer_cost_are_separate():
    r = calculate(salary())
    assert (r["gross"],r["discounts"],r["net"]) == (3500000,315000,3185000)
    assert (r["employer_contribution"],r["employer_cost"]) == (577500,4077500)


def test_family_and_reimbursements_do_not_increase_default_ips_base():
    r = calculate(salary(family="200000",reimbursements="100000"))
    assert r["discounts"] == 315000
    assert r["net"] == 3485000


def test_rounding_half_up_per_item():
    r = calculate(salary(salary="305",days_paid="15",apply_ips=""))
    assert r["gross"] == 153
    assert calculate(dict(kind="aguinaldo",issued_date="2026-09-09",year="2026",annual_remuneration="6"))["net"] == 1


@pytest.mark.parametrize("invalid", ["-1", "NaN", "Infinity", "abc", "1.01", "1e100"])
def test_invalid_money_rejected(invalid):
    with pytest.raises(CalculationError):
        calculate(salary(salary=invalid))


def test_negative_net_is_rejected():
    with pytest.raises(CalculationError):
        calculate(salary(other_discount="4000000",discount_reason="Ejemplo"))


def test_zero_ips_base_is_preserved_and_requires_reason():
    assert calculate(salary(ips_base="0",ips_reason="Base cero revisada en ejemplo"))["discounts"] == 0
    with pytest.raises(CalculationError):
        calculate(salary(ips_base="0"))


def test_base_can_exceed_gross_when_reviewed():
    r=calculate(salary(ips_base="4000000",ips_reason="Base mínima aplicable revisada"))
    assert r["discounts"] == 360000


def test_six_month_fraction_is_strict():
    r = calculate(settlement())
    assert next(x["amount"] for x in r["earnings"] if "Indemnización" in x["label"]) == 3000000
    data=settlement()
    data["end_date"]="2026-07-02"
    r=calculate(data)
    assert next(x["amount"] for x in r["earnings"] if "Indemnización" in x["label"]) == 4500000


def test_stability_partial_and_no_automatic_double_severance():
    data=settlement()
    data["start_date"]="2010-01-01"
    r=calculate(data)
    assert r["partial"]
    assert not any("Indemnización" in row["label"] or "Preaviso" in row["label"] for row in r["earnings"])


def test_resignation_does_not_auto_deduct_notice():
    data=settlement()
    data["reason"]="resignation"
    r=calculate(data)
    assert not r["deductions"]
    assert r["net"] == 1500000


def test_settlement_ips_requires_reviewed_base_and_note():
    data=settlement(apply_ips="on")
    with pytest.raises(CalculationError):
        calculate(data)
    data.update(ips_base="0",ips_reason="Composición del egreso revisada")
    assert calculate(data)["net"] > 0


def test_protected_entitlements_not_used_for_generic_debts():
    with pytest.raises(CalculationError):
        calculate(settlement(other_discount="100",discount_reason="Deuda"))


def test_annual_base_includes_current_remuneration_and_prior_payment_bound():
    data=settlement()
    data.update(days_paid="30",annual_remuneration="100")
    with pytest.raises(CalculationError):
        calculate(data)
    with pytest.raises(CalculationError):
        calculate(dict(kind="aguinaldo",issued_date="2026-09-09",year="2026",annual_remuneration="1200",aguinaldo_paid="101"))


def test_vacation_uses_higher_minimum():
    r=calculate(dict(kind="vacation",salary="2000000",legal_minimum="3000000",
                     vacation_quantity="12",issued_date="2026-09-09"))
    assert r["net"] == 1200000


def test_night_overtime_uses_ordinary_night_hour():
    r=calculate(dict(kind="hours",hour_type="night_extra",hourly_base="15000",
                     hours="2",issued_date="2026-09-09"))
    assert r["net"] == 60000


def test_pdf_and_csv_preserve_totals_and_copies():
    result=calculate(salary())
    payload=build_liquidation_pdf(result)
    reader=PdfReader(io.BytesIO(payload))
    text="\n".join(p.extract_text() for p in reader.pages)
    assert "ORIGINAL / EMPLEADOR" in text and "DUPLICADO / TRABAJADOR" in text
    assert text.count("3.185.000") == 2
    assert all(abs(float(p.mediabox.width)-595.28)<1 for p in reader.pages)
    csv=build_liquidation_csv(result).decode("utf-8-sig")
    assert "Neto a percibir;3185000" in csv
    assert "Costo empleador;4077500" in csv


def test_pdf_long_settlement_and_csv_formula_injection():
    data=settlement()
    data.update(two_copies="on",notes="Revisión documentada. "*25,employee="=SUM(A1:A5)",
                employer="<Sociedad & Asociados>",pending_days="12",double_days="6")
    result=calculate(data)
    pages=PdfReader(io.BytesIO(build_liquidation_pdf(result))).pages
    assert len(pages) >= 2
    assert "'=SUM(A1:A5)" in build_liquidation_csv(result).decode("utf-8-sig")


@pytest.fixture
def web_case(tmp_path,monkeypatch):
    """Isolated route integration: never read or migrate a production database."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.runtime import app
    from app import main as core
    from app.database import Base
    from app.models import Studio,Company,Employee,User
    engine=create_engine(f"sqlite:///{tmp_path / 'routes.db'}",connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    db=Session()
    studio=Studio(name="Estudio sintético")
    outsider=Studio(name="Otro estudio sintético")
    db.add_all([studio,outsider]);db.flush()
    company=Company(studio_id=studio.id,legal_name="Empresa sintética",ruc="80000001-0")
    foreign=Company(studio_id=outsider.id,legal_name="Empresa ajena",ruc="80000002-0")
    db.add_all([company,foreign]);db.flush()
    employee=Employee(company_id=company.id,full_name="Persona sintética",document_number="1000001",base_salary=3500000)
    other=Employee(company_id=foreign.id,full_name="Persona ajena",document_number="1000002",base_salary=3500000)
    user=User(studio_id=studio.id,full_name="Contador sintético",email="synthetic@example.invalid",
              password_hash="unused",role="contador")
    db.add_all([employee,other,user]);db.commit()
    box={"user":user}
    def session():
        with Session() as session:
            yield session
    def auth():
        return box["user"]
    previous=dict(app.dependency_overrides)
    app.dependency_overrides[core.get_db]=session
    app.dependency_overrides[core.require_user]=auth
    monkeypatch.setattr(core,"settings",replace(core.settings,csrf_enabled=True))
    client=TestClient(app)
    yield client,db,box,company,employee,other
    client.close()
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
    db.close();engine.dispose()


def token(client,path="/herramientas"):
    page=client.get(path)
    assert page.status_code == 200, page.text
    return re.search(r'name="csrf_token" value="([^"]+)"',page.text).group(1)


def test_public_flow_csrf_validation_xss_and_download(web_case):
    client,*_=web_case
    csrf=token(client)
    assert client.post("/herramientas/calcular",data=salary()).status_code == 403
    data=salary(employee="<script>alert(1)</script>",csrf_token=csrf)
    response=client.post("/herramientas/calcular",data=data)
    assert response.status_code == 200, response.text
    assert "3.185.000" in response.text and "&lt;script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text
    pdf=client.post("/herramientas/exportar/pdf",data=data)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["cache-control"] == "no-store"
    data["salary"]="-1"
    invalid=client.post("/herramientas/calcular",data=data)
    assert invalid.status_code == 422 and "Revisá los datos" in invalid.text


def test_private_context_save_snapshot_and_tenant_boundaries(web_case,monkeypatch):
    client,db,box,company,employee,other=web_case
    csrf=token(client,f"/app/liquidaciones?company_id={company.id}&employee_id={employee.id}")
    data=salary(company_id=str(company.id),employee_id=str(employee.id),csrf_token=csrf,employer="Falsificado")
    response=client.post("/app/liquidaciones/guardar",data=data,follow_redirects=False)
    assert response.status_code == 303,response.text
    url=response.headers["location"]
    saved=client.get(url)
    assert saved.status_code == 200 and "Empresa sintética" in saved.text and "Falsificado" not in saved.text
    from app import calculator_routes as routes
    monkeypatch.setattr(routes,"calculate",lambda _: (_ for _ in ()).throw(AssertionError("Snapshot must not recalculate")))
    export=client.get(url+"/exportar/pdf")
    assert export.status_code == 200
    assert "3.185.000" in "".join(p.extract_text() for p in PdfReader(io.BytesIO(export.content)).pages)
    assert client.get(f"/app/liquidaciones?company_id={other.company_id}").status_code == 404
    assert client.get(f"/app/liquidaciones?company_id={company.id}&employee_id={other.id}").status_code == 404
    box["user"].studio_id=999999
    assert client.get(url).status_code == 404
    assert client.get(url+"/exportar/pdf").status_code == 404


def test_company_role_cannot_save(web_case):
    client,db,box,company,employee,_=web_case
    csrf=token(client)
    box["user"].role="empresa"
    box["user"].company_id=company.id
    response=client.post("/app/liquidaciones/guardar",data=salary(csrf_token=csrf,company_id=str(company.id),employee_id=str(employee.id)))
    assert response.status_code == 403


def test_payroll_zero_base_persistence_and_closed_edit_guard(web_case):
    client,db,box,company,employee,_=web_case
    from app.models import Payroll,PayrollLine,PayrollComplianceDetail
    payroll=Payroll(company_id=company.id,period="2026-09")
    db.add(payroll);db.flush()
    line=PayrollLine(payroll_id=payroll.id,employee_id=employee.id,base_salary=3500000,
                     gross=3500000,net=3500000,ips_employee=0,total_discounts=0,
                     ips_base=0,ips_rate=Decimal("9.00"),ips_basis_note="Base revisada")
    db.add(line);db.commit()
    csrf=token(client)
    data=dict(csrf_token=csrf,base_salary="3500000",ips_base="0",ips_rate="9",
              ips_basis_note="Base revisada",days_worked="22")
    response=client.post(f"/app/payrolls/{payroll.id}/lines/{line.id}",data=data,follow_redirects=False)
    assert response.status_code == 303,response.text
    db.expire_all();db.refresh(line)
    assert line.ips_base == 0 and line.ips_employee == 0 and line.net == 3500000
    detail=db.query(PayrollComplianceDetail).filter_by(payroll_line_id=line.id).one()
    assert detail.days_worked == 22
    assert client.get(f"/app/payrolls/{payroll.id}").status_code == 200
    pdf=client.get(f"/app/payrolls/{payroll.id}/recibos.pdf?line_id={line.id}")
    assert pdf.status_code == 200
    data["other_discount"]="4000000";data["other_discount_note"]="Prueba"
    assert client.post(f"/app/payrolls/{payroll.id}/lines/{line.id}",data=data).status_code == 422
    payroll.status="Cerrada";db.commit()
    assert client.post(f"/app/payrolls/{payroll.id}/lines/{line.id}",data=data).status_code == 409


def test_migration_adds_columns_without_rewriting_history(tmp_path):
    from sqlalchemy import create_engine,text,inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine=create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE payroll_lines (id INTEGER PRIMARY KEY, gross INTEGER, ips_employee INTEGER, net INTEGER)"))
        conn.execute(text("INSERT INTO payroll_lines VALUES (1, 3500000, 315000, 3185000)"))
        spec=importlib.util.spec_from_file_location("migration6","alembic/versions/0006_payroll_calculation_inputs.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        row=conn.execute(text("SELECT gross, ips_employee, net, ips_base, ips_rate FROM payroll_lines")).one()
        assert tuple(row) == (3500000,315000,3185000,None,None)
        assert {"ips_base","ips_rate","ips_basis_note","other_discount_note"} <= {c["name"] for c in inspect(conn).get_columns("payroll_lines")}
    engine.dispose()
