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


@pytest.mark.parametrize("reported,difference", [("3185000",0),("3000000",185000),("3500000",-315000),("0",3185000)])
def test_receipt_review_preserves_salary_and_reports_signed_difference(reported, difference):
    result = calculate(salary(reported_net=reported))
    assert result["net"] == 3185000
    assert result["receipt_review"] == dict(reported=int(reported), difference=difference)
    pdf_text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(build_liquidation_pdf(result))).pages)
    assert "Neto informado en el recibo" in pdf_text
    assert "no acredita un pago" in pdf_text
    assert "Diferencia (calculado menos informado)" in build_liquidation_csv(result).decode("utf-8-sig")


def test_receipt_review_is_optional_and_rejects_invalid_amounts():
    assert "receipt_review" not in calculate(salary())
    for invalid in ("-1", "NaN", "10.5", "1.000.000"):
        with pytest.raises(CalculationError) as error:
            calculate(salary(reported_net=invalid))
        assert error.value.field == "reported_net"


def comparison_form(csrf, a=None, b=None):
    a = salary() if a is None else a
    b = salary(salary="4000000") if b is None else b
    return dict(csrf_token=csrf, kind=a["kind"], label_a="Base", label_b="Alternativa",
                **{"a_"+k:v for k,v in a.items() if k != "kind"},
                **{"b_"+k:v for k,v in b.items() if k != "kind"})


def test_comparison_calculates_two_independent_scenarios_and_exports(web_case):
    client, *_ = web_case
    csrf = token(client, "/herramientas/comparar?tipo=salary")
    data = comparison_form(csrf)
    response = client.post("/herramientas/comparar", data=data)
    assert response.status_code == 200
    for expected in ("3.185.000", "3.640.000", "455.000", "582.500", "Datos que cambian"):
        assert expected in response.text
    ids = re.findall(r'\bid="([^"]+)"', response.text)
    assert len(ids) == len(set(ids)), "Comparison forms and results require unique ids"
    for side, net in (("a","3.185.000"),("b","3.640.000")):
        exported = client.post(f"/herramientas/comparar/exportar/{side}/pdf", data=data)
        assert exported.status_code == 200
        assert f"escenario-{side}-" in exported.headers["content-disposition"]
        assert net in "".join(p.extract_text() for p in PdfReader(io.BytesIO(exported.content)).pages)
        assert exported.headers["cache-control"] == "no-store"
    csv = client.post("/herramientas/comparar/exportar/b/csv", data=data)
    assert "Neto a percibir;3640000" in csv.content.decode("utf-8-sig")
    assert client.post("/herramientas/comparar/exportar/c/pdf", data=data).status_code == 404


def test_comparison_validation_csrf_partial_results_and_escaping(web_case):
    client, *_ = web_case
    data = comparison_form(token(client), salary(salary="-1"), salary(salary=""))
    invalid = client.post("/herramientas/comparar",data=data)
    assert invalid.status_code == 422
    assert "Escenario A:" in invalid.text and "Escenario B:" in invalid.text
    assert 'id="labor-result"' not in invalid.text
    assert client.post("/herramientas/comparar/exportar/a/pdf",data=data).status_code == 422
    data.pop("csrf_token")
    assert client.post("/herramientas/comparar",data=data).status_code == 403
    data = comparison_form(token(client), settlement(protected="on"), settlement())
    data["label_a"] = '<script>alert("x")</script>'
    partial = client.post("/herramientas/comparar", data=data)
    assert partial.status_code == 200
    assert "Hay un escenario parcial" in partial.text
    assert '<script>alert("x")</script>' not in partial.text
    assert '&lt;script&gt;' in partial.text
    huge = comparison_form(token(client))
    huge["a_notes"] = "x" * 65000
    assert client.post("/herramientas/comparar", data=huge).status_code == 413


@pytest.mark.parametrize("profile", ["empresa","contador","abogado","empleado"])
def test_each_profile_has_actionable_guide_and_safe_examples(web_case, profile):
    from app.models import CalculationRecord
    client, db, *_ = web_case
    response = client.get("/empezar",params={"perfil":profile})
    assert response.status_code == 200
    assert 'aria-current="page"' in response.text
    assert "DATOS FICTICIOS" in response.text
    assert "registro(s) disponible(s)" not in response.text
    before = db.query(CalculationRecord).count()
    demo = client.get("/herramientas?tipo=salary&ejemplo=true")
    assert 'value="3500000"' in demo.text and "Estás usando datos ficticios" in demo.text
    assert 'id="labor-result"' not in demo.text
    assert db.query(CalculationRecord).count() == before
    assert client.get("/empezar?perfil=no-existe").status_code == 404


def test_comparison_demo_is_executable_and_does_not_persist(web_case):
    from html.parser import HTMLParser
    from app.models import CalculationRecord
    client, db, *_ = web_case
    response = client.get("/herramientas/comparar?tipo=settlement&ejemplo=true")
    class FormValues(HTMLParser):
        def __init__(self):
            super().__init__()
            self.data, self.active, self.select, self.textarea = {}, False, None, None
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "form":
                self.active = attrs.get("id") == "labor-form"
            if not self.active:
                return
            if tag == "input" and attrs.get("name"):
                if attrs.get("type") != "checkbox" or "checked" in attrs:
                    self.data[attrs["name"]] = attrs.get("value", "")
            elif tag == "select":
                self.select = attrs["name"]
            elif tag == "option" and self.select:
                if self.select not in self.data or "selected" in attrs:
                    self.data[self.select] = attrs.get("value", "")
            elif tag == "textarea":
                self.textarea = attrs["name"]
                self.data[self.textarea] = ""
        def handle_data(self, text):
            if self.active and self.textarea:
                self.data[self.textarea] += text
        def handle_endtag(self, tag):
            if tag == "form": self.active = False
            elif tag == "select": self.select = None
            elif tag == "textarea": self.textarea = None
    form = FormValues()
    form.feed(response.text)
    data = form.data
    result = client.post("/herramientas/comparar", data=data)
    assert result.status_code == 200, result.text[:500]
    assert "9.000.000" in result.text and "1.500.000" in result.text and "-7.500.000" in result.text
    assert db.query(CalculationRecord).count() == 0


def test_company_scope_fails_closed_without_valid_assignment(web_case):
    from app import main as core
    client, db, box, company, employee, other = web_case
    box["user"].role = "empresa"
    for assignment in (None, other.company_id):
        box["user"].company_id = assignment
        assert core.company_ids_for_user(db, box["user"]) == []
        assert client.get(f"/app/employees/{employee.id}").status_code == 404
    box["user"].company_id = company.id
    assert core.company_ids_for_user(db, box["user"]) == [company.id]
    guide = client.get("/app/guia")
    assert guide.status_code == 200
    assert "1 registro(s) disponible(s)" in guide.text and "0 registro(s) disponible(s)" in guide.text
    assert "empresa vinculada" in guide.text and "Nóminas</h2>" not in guide.text


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


@pytest.mark.parametrize("path", [
    "/app/liquidaciones?company_id=&employee_id=",
    "/app/employees?company_id=&q=Persona",
    "/app/calendar?company_id=&employee_id=",
    "/app/calculations?company_id=&employee_id=",
    "/app/certificates?company_id=&employee_id=",
    "/app/reports?company_id=&employee_id=",
    "/app/ai?company_id=&employee_id=",
    "/app/compliance?company_id=",
])
def test_empty_browser_filters_are_optional(web_case, path):
    client, *_ = web_case
    response = client.get(path)
    assert response.status_code == 200, response.text[:600]


def test_select_company_before_employee_and_clear_selection(web_case):
    client, _, _, company, employee, _ = web_case
    response = client.get("/app/liquidaciones", params={"company_id": company.id, "employee_id": ""})
    assert response.status_code == 200, response.text[:600]
    assert employee.full_name in response.text
    assert f'value="{employee.id}"' in response.text
    assert client.get("/app/liquidaciones?company_id=&employee_id=").status_code == 200


def test_normal_account_login_csrf_private_pages_and_logout(web_case):
    from app import main as core
    from app.auth import hash_password
    from app.runtime import app
    client, db, box, company, employee, other = web_case
    user = box["user"]
    user.password_hash = hash_password("Synthetic-login-test-914!")
    db.commit()
    app.dependency_overrides.pop(core.require_user)
    assert client.get("/app", follow_redirects=False).headers["location"] == "/login"
    csrf = token(client, "/login")
    response = client.post("/login", data={"email": user.email, "password": "Synthetic-login-test-914!", "csrf_token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    for path in ("/app", "/app/companies", "/app/employees", "/app/payrolls", "/app/liquidaciones", "/app/documents"):
        assert client.get(path).status_code == 200, path
    assert client.get("/admin").status_code == 403
    assert client.get("/app/users").status_code == 403
    assert client.get(f"/app/companies/{other.company_id}").status_code == 404
    assert client.get(f"/app/employees/{other.id}").status_code == 404
    csrf = token(client, "/app/liquidaciones")
    created = client.post("/app/companies", data=dict(csrf_token=csrf, legal_name="Nueva empresa de QA", ruc="80099999-1"), follow_redirects=False)
    assert created.status_code == 303
    company_id = int(created.headers["location"].rsplit("/", 1)[1])
    created = client.post("/app/employees", data=dict(csrf_token=csrf, company_id=company_id,
        full_name="Funcionario de QA", document_number="1999999", position="Auxiliar", admission_date="2024-01-01",
        birth_date="", branch_id="", base_salary="3500000", contract_type="Tiempo indefinido", payment_frequency="Mensual", ips_contributor="on"), follow_redirects=False)
    assert created.status_code == 303, created.text
    from app.models import Employee
    new_employee = db.query(Employee).filter_by(company_id=company_id).one()
    data = salary(csrf_token=csrf, company_id=company_id, employee_id=new_employee.id)
    calculated = client.post("/app/liquidaciones/calcular", data=data)
    assert calculated.status_code == 200 and "3.185.000" in calculated.text
    saved = client.post("/app/liquidaciones/guardar", data=data, follow_redirects=False)
    assert saved.status_code == 303
    for fmt in ("pdf", "csv"):
        exported = client.get(saved.headers["location"] + "/exportar/" + fmt)
        assert exported.status_code == 200
    assert client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False).status_code == 303
    assert client.get("/app/liquidaciones", follow_redirects=False).headers["location"] == "/login"


def test_private_exports_keep_identity_scope_and_validation_context(web_case):
    client, _, _, company, employee, other = web_case
    data = salary(csrf_token=token(client), company_id=company.id, employee_id=employee.id, employee="Alterado")
    pdf = client.post("/app/liquidaciones/exportar/pdf", data=data)
    assert pdf.status_code == 200
    assert "2026-09-Persona-sintetica.pdf" in pdf.headers["content-disposition"]
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Persona sintética" in text and "Alterado" not in text
    data["employee_id"] = other.id
    assert client.post("/app/liquidaciones/exportar/pdf", data=data).status_code == 404
    data.update(employee_id=employee.id, salary="-1")
    invalid = client.post("/app/liquidaciones/exportar/pdf", data=data)
    assert invalid.status_code == 422
    assert "CENTRO PROFESIONAL" in invalid.text and "Empresa sintética" in invalid.text


def test_copy_calculation_preserves_original_and_needs_recalculation(web_case):
    import json
    from app.models import CalculationRecord
    client, db, box, company, employee, _ = web_case
    data = salary(csrf_token=token(client), company_id=company.id, employee_id=employee.id, salary="4000000", notes="Ejemplo anterior")
    saved = client.post("/app/liquidaciones/guardar", data=data, follow_redirects=False)
    path = saved.headers["location"]
    record = db.get(CalculationRecord, int(path.rsplit("/", 1)[1]))
    original = record.result_json
    copied = client.get(path + "/copiar")
    assert copied.status_code == 200
    assert 'value="4000000"' in copied.text and "Ejemplo anterior" in copied.text
    assert 'id="labor-result"' not in copied.text
    assert "El registro original se conserva" in copied.text
    data.update(salary="5000000")
    second = client.post("/app/liquidaciones/guardar", data=data, follow_redirects=False)
    assert second.headers["location"] != path
    db.refresh(record)
    assert record.result_json == original and json.loads(original)["net"] == 3640000
    box["user"].studio_id = 999999
    assert client.get(path + "/copiar").status_code == 404


def test_calendar_handles_february_29_admission(web_case, monkeypatch):
    from app import main as core
    client, db, _, company, employee, _ = web_case
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 15)
    monkeypatch.setattr(core, "date", FixedDate)
    employee.admission_date = date(2024, 2, 29)
    db.commit()
    response = client.get("/app/calendar", params={"company_id": company.id})
    assert response.status_code == 200
    assert "28/02/2026" in response.text


def test_certificate_context_rejects_foreign_employee_without_company(web_case):
    client, _, _, company, employee, other = web_case
    assert client.get(f"/app/certificates?employee_id={other.id}").status_code == 404
    own = client.get(f"/app/certificates?employee_id={employee.id}")
    assert own.status_code == 200 and company.legal_name in own.text


def test_assistant_results_are_scoped_to_authorized_companies(web_case):
    from app.models import AIInteraction, Company
    client, db, box, company, employee, other = web_case
    another_company = Company(studio_id=company.studio_id, legal_name="Otra empresa del estudio", ruc="80099998-2")
    db.add(another_company); db.flush()
    own = AIInteraction(studio_id=company.studio_id, company_id=company.id, purpose="control", response_text="Resultado autorizado")
    foreign = AIInteraction(studio_id=other.company.studio_id, company_id=other.company_id, purpose="control", response_text="Resultado privado ajeno")
    sibling = AIInteraction(studio_id=company.studio_id, company_id=another_company.id, purpose="control", response_text="Otra empresa privada")
    db.add_all([own, foreign, sibling]); db.commit()
    assert "Resultado autorizado" in client.get(f"/app/ai?result={own.id}").text
    assert client.get(f"/app/ai?result={foreign.id}").status_code == 404
    box["user"].role = "empresa"
    box["user"].company_id = company.id
    assert client.get(f"/app/ai?result={sibling.id}").status_code == 404
    assert "Otra empresa del estudio" not in client.get("/app/ai").text


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


def test_legacy_calculator_rejects_negative_net_and_unknown_employee(web_case):
    client,db,box,company,employee,_=web_case
    csrf=token(client)
    data=dict(csrf_token=csrf,calculation_type="salary",company_id=str(company.id),
              employee_id=str(employee.id),gross="3500000",other_discount="4000000")
    assert client.post("/app/calculations",data=data).status_code == 422
    data.update(other_discount="0",employee_id="9999999")
    assert client.post("/app/calculations",data=data).status_code == 404
    data.update(employee_id=str(employee.id),gross="NaN")
    assert client.post("/app/calculations",data=data).status_code == 422
