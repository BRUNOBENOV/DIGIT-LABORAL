from __future__ import annotations

from datetime import date
from pathlib import Path
import re
import uuid

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete, select

from app.auth import hash_password
from app.database import SessionLocal
from app.main import APP_VERSION, app
from app.models import (
    AuditLog, CalculationRecord, Company, CompanyBranding, CompanyComplianceProfile,
    CompanyRequest, Employee, EmployeeComplianceProfile, LaborOperation, MedicalExam,
    Notification, RequestWorkflow, SecurityEvent, Studio, User, UserSecurity, Vacation,
)


PASSWORD = "Entity-QA-Only-2026!"


def login(client, email):
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    response = client.post("/login", data={"email": email, "password": PASSWORD, "csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303


@pytest.fixture(scope="module")
def entity_directory():
    """A large, isolated synthetic tenant; the application never uses production data."""
    marker = "Entity-"+uuid.uuid4().hex[:12]
    with TestClient(app) as client:
        with SessionLocal() as db:
            studio = Studio(name=marker, company_limit=2000)
            foreign_studio = Studio(name=marker+" Foreign")
            db.add_all([studio, foreign_studio]); db.flush()
            companies = [Company(studio_id=studio.id, company_code=10000+i, legal_name=f"AA {marker} Company {i:04}", ruc=f"QA-{marker}-{i}", status="Activa") for i in range(949)]
            companies[0].company_code = 1207; companies[0].legal_name = f"ZZ {marker} AEROMAR"
            companies[0].legal_representative = "Representante principal"
            companies[1].company_code = 1359; companies[1].legal_name = f"ZZ {marker} CHU"
            companies[2].status = "Archivada"
            foreign = Company(studio_id=foreign_studio.id, company_code=1207, legal_name=marker+" AEROMAR Foreign", ruc=marker+"-Foreign")
            db.add_all(companies+[foreign]); db.flush()
            main, second, archived_company = companies[0], companies[1], companies[2]
            employees = [Employee(company_id=main.id, employee_code=200000+i, full_name=f"Bulk {marker} Worker {i:05}", document_number=f"CI-{marker}-{i}", admission_date=date(2020, 1, 1), base_salary=4_321_000, status="Activo") for i in range(1, 11101)]
            target = employees[7000]; target.full_name = "ZZ Brúno Benítez"; target.document_number = "4.332.400"
            employees[-1].status = "Desvinculado"
            employees[-2].status = "Archivado"
            duplicate = Employee(company_id=second.id, employee_code=207001, full_name="Bruno de otra empresa", document_number="9.333.111", admission_date=date(2020,1,1))
            foreign_employee = Employee(company_id=foreign.id, employee_code=207001, full_name="Bruno Foreign", document_number="4.332.400", admission_date=date(2020,1,1))
            archived_worker = Employee(company_id=archived_company.id, employee_code=207001, full_name="Bruno empresa archivada", document_number="7.777.777", admission_date=date(2020,1,1))
            db.add_all(employees+[duplicate,foreign_employee,archived_worker]); db.flush()
            db.add(CompanyBranding(company_id=main.id, signature_name="No debe reemplazar al representante", signature_title="Director", primary_color="#05256D"))
            db.add(Vacation(employee_id=target.id, period_year=2026, entitled_days=12, used_days=6, start_date=date(2026,8,1), end_date=date(2026,8,6)))
            calculation = CalculationRecord(company_id=main.id, employee_id=target.id, calculation_type="salary", amount=4_321_000, status="Revisar")
            medical = MedicalExam(company_id=main.id, employee_id=target.id, exam_code=marker+"-EX", exam_type="Ingreso", exam_date=date(2026,1,1), expires_on=date(2027,1,1), result="Apto")
            operation = LaborOperation(company_id=main.id, employee_id=target.id, operation_type="hours", title=marker, effective_date=date(2026,1,1))
            db.add_all([calculation,medical,operation])
            users=[]
            for role in ("administrador","empresa","abogado"):
                user = User(studio_id=studio.id, company_id=main.id if role=="empresa" else None, email=marker+"-"+role+"@qa.test", full_name=marker+role, password_hash=hash_password(PASSWORD), role=role, active=True, must_change_password=False)
                db.add(user); db.flush(); db.add(UserSecurity(user_id=user.id)); users.append(user)
            request = CompanyRequest(company_id=second.id, request_type="Documento laboral", subject=marker, detail=marker)
            db.add(request); db.flush(); db.add(RequestWorkflow(request_id=request.id, assigned_user_id=users[2].id))
            db.flush()
            data={"marker":marker,"company":main.id,"second":second.id,"target":target.id,
                  "archived_company":archived_company.id,"foreign_company":foreign.id,"foreign_employee":foreign_employee.id,
                  "archived":employees[-2].id,"terminated":employees[-1].id,
                  "calculation":calculation.id,"medical":medical.id,"operation":operation.id,
                  "emails":{user.role:user.email for user in users}}
            company_ids=[company.id for company in companies]+[foreign.id]
            user_ids=[user.id for user in users]; studio_ids=[studio.id,foreign_studio.id]
            db.commit()
        login(client,data["emails"]["administrador"])
        try:
            yield client,data
        finally:
            with SessionLocal() as db:
                employee_ids=select(Employee.id).where(Employee.company_id.in_(company_ids))
                for model in (MedicalExam,LaborOperation,CalculationRecord): db.execute(delete(model).where(model.company_id.in_(company_ids)))
                db.execute(delete(Vacation).where(Vacation.employee_id.in_(employee_ids)))
                db.execute(delete(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id.in_(employee_ids)))
                db.execute(delete(RequestWorkflow).where(RequestWorkflow.request_id.in_(select(CompanyRequest.id).where(CompanyRequest.company_id.in_(company_ids)))))
                db.execute(delete(CompanyRequest).where(CompanyRequest.company_id.in_(company_ids)))
                for model in (CompanyBranding,CompanyComplianceProfile): db.execute(delete(model).where(model.company_id.in_(company_ids)))
                db.execute(delete(Notification).where(Notification.recipient_user_id.in_(user_ids)))
                db.execute(delete(SecurityEvent).where(SecurityEvent.user_id.in_(user_ids)))
                db.execute(delete(UserSecurity).where(UserSecurity.user_id.in_(user_ids)))
                db.execute(delete(User).where(User.id.in_(user_ids)))
                db.execute(delete(AuditLog).where(AuditLog.studio_id.in_(studio_ids)))
                db.execute(delete(Employee).where(Employee.company_id.in_(company_ids)))
                db.execute(delete(Company).where(Company.id.in_(company_ids)))
                db.execute(delete(Studio).where(Studio.id.in_(studio_ids)))
                db.commit()


def lookup(client, kind, **params):
    response=client.get("/api/selectors/"+kind,params=params)
    assert response.status_code==200,response.text[:400]
    assert response.headers["cache-control"]=="no-store, max-age=0"
    return response.json()


def test_company_code_and_name_search_are_bounded_and_tenant_scoped(entity_directory):
    client,data=entity_directory
    by_code=lookup(client,"companies",q="1207")
    assert by_code["items"][0]["id"]==data["company"]
    assert by_code["items"][0]["label"].startswith("1207 - ")
    assert lookup(client,"companies",q="CHU")["items"][0]["id"]==data["second"]
    result=lookup(client,"companies",q=data["marker"],limit=10000)
    assert len(result["items"])==20 and result["has_more"]
    assert len(lookup(client,"companies")["items"])==10
    assert not lookup(client,"companies",q="%_")["items"]
    assert data["foreign_company"] not in {item["id"] for item in lookup(client,"companies",q="AEROMAR")["items"]}


@pytest.mark.parametrize("query",["207001","Bruno Benitez","brúno BENÍTEZ","4332400","4.332.400"])
def test_employee_search_matches_code_name_accents_and_formatted_ci(entity_directory,query):
    client,data=entity_directory
    result=lookup(client,"employees",q=query,company_id=data["company"])
    assert result["items"][0]["id"]==data["target"]
    assert result["items"][0]["label"]=="207001 - ZZ Brúno Benítez"
    assert all(item["company_id"]==data["company"] for item in result["items"])
    assert "dataset" not in result["items"][0]


def test_employee_scope_limits_and_authorization_cannot_be_bypassed(entity_directory):
    client,data=entity_directory
    result=lookup(client,"employees",q="207001",scope="all")
    assert len(result["items"])==3
    assert lookup(client,"employees",q="Bruno Benitez",company_id=data["second"])["items"]==[]
    all_workers=lookup(client,"employees",q="Bulk",limit=99999)
    assert len(all_workers["items"])==20 and all_workers["has_more"]
    assert client.get("/api/selectors/employees",params={"company_id":data["foreign_company"]}).status_code==404
    assert client.get("/api/selectors/employees",params={"selected_id":data["foreign_employee"]}).status_code==404
    assert client.get("/api/selectors/companies",params={"selected_id":data["foreign_company"]}).status_code==404
    for key in ("archived","terminated"):
        assert client.get("/api/selectors/employees",params={"selected_id":data[key],"scope":"active"}).status_code==404
        assert lookup(client,"employees",selected_id=data[key],scope="all")["items"][0]["id"]==data[key]
    assert client.get("/api/selectors/companies",params={"selected_id":data["archived_company"],"scope":"current"}).status_code==404
    assert client.get("/api/selectors/employees",params={"scope":"invalid"}).status_code==422


def test_confirmed_selection_returns_legacy_form_and_certificate_metadata(entity_directory):
    client,data=entity_directory
    company=lookup(client,"companies",selected_id=data["company"])["items"][0]
    assert company["dataset"]["signature"]=="Representante principal"
    assert company["dataset"]["signatureTitle"]=="Representante legal"
    assert company["dataset"]["primary"]=="#05256D"
    employee=lookup(client,"employees",selected_id=data["target"],company_id=data["company"])["items"][0]
    assert employee["dataset"]["company"]==str(data["company"])
    assert employee["dataset"]["salary"]=="4321000"
    assert employee["dataset"]["admission"]=="2020-01-01"
    assert employee["dataset"]["vacationStart"]=="2026-08-01"
    assert employee["dataset"]["vacationYear"]=="2026"
    assert client.get("/api/selectors/employees",params={"selected_id":data["target"],"company_id":data["second"]}).status_code==404


@pytest.mark.parametrize("path",[
    "/app/employees","/app/sections","/app/calculations?tipo=salary","/app/calculations/periodos",
    "/app/liquidaciones?tipo=settlement","/app/payrolls","/app/vacations","/app/aguinaldo",
    "/app/calculation-operations?tipo=hours","/app/employee-history","/app/requests",
    "/app/certificates","/app/medical-exams","/app/documents","/app/calendar","/app/users",
    "/app/ai","/app/compliance","/app/reports/listado-empleado","/app/reports/liquidaciones-salarios",
])
def test_all_modules_render_bounded_searchable_choices_with_large_tenant(entity_directory,path):
    client,data=entity_directory
    response=client.get(path)
    assert response.status_code==200,(path,response.text[:400])
    soup=BeautifulSoup(response.text,"html.parser")
    selects=soup.select('select[data-searchable-entity]')
    assert selects,path
    for select_node in selects:
        assert len(select_node.select("option"))<=12,(path,select_node.get("id"))
    assert f"entity-selects.js?v={APP_VERSION}" in response.text


def test_selected_records_outside_seed_remain_selected_in_filters_and_editors(entity_directory):
    client,data=entity_directory
    for path,params,selector in [
        ("/app/reports/listado-empleado",{"company_id":data["company"],"employee_id":data["target"]},'select[name="employee_id"]'),
        ("/app/certificates",{"calculation_id":data["calculation"]},'#certificateEmployee'),
        ("/app/medical-exams",{"edit_id":data["medical"]},'#medicalExamEmployee'),
        ("/app/calculation-operations",{"tipo":"hours","edit":data["operation"]},'form[method="post"] select[name="employee_id"]'),
    ]:
        response=client.get(path,params=params)
        assert response.status_code==200,(path,response.text[:300])
        options=BeautifulSoup(response.text,"html.parser").select(selector+" option[selected]")
        assert str(data["target"]) in {option["value"] for option in options},path


@pytest.mark.parametrize("role",["empresa","abogado"])
def test_lookup_respects_company_accounts_and_lawyer_assignments(entity_directory,role):
    _,data=entity_directory
    with TestClient(app) as client:
        login(client,data["emails"][role])
        expected=data["company"] if role=="empresa" else data["second"]
        assert {item["id"] for item in lookup(client,"companies")["items"]}=={expected}
        assert {item["company_id"] for item in lookup(client,"employees",q="207001")["items"]}=={expected}


def test_all_company_and_employee_selects_use_the_shared_adapter_and_no_anonymous_data():
    root=Path(__file__).resolve().parents[1]
    total=0
    for path in (root/"app/templates").rglob("*.html"):
        for select_node in re.findall(r'<select\b[^>]*>',path.read_text()):
            if re.search(r'name="(?:company_id|employee_id)"|id="(?:sectionCompany|sectionEditorCompany)"',select_node):
                assert 'data-searchable-entity=' in select_node,path.name
                total+=1
    assert total>=54
    with TestClient(app) as client:
        response=client.get("/api/selectors/employees?q=Bruno",follow_redirects=False)
        assert response.status_code==303 and response.headers["location"]=="/login"
