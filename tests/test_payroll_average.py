from calendar import monthrange
from datetime import UTC, date, datetime
import io
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest
from sqlalchemy import select

from app import main as core
from app.labor_calculator import CalculationError
from app.models import CalculationRecord, EmployeeComplianceProfile, Payroll, PayrollComplianceDetail, PayrollLine
from app.payroll_average import propose_monthly_average, verify_average_selection
from tests.test_labor_suite import token, web_case
from tests.test_settlement_legal_cases import settlement_data


@pytest.fixture
def average_case(web_case):
    client, db, box, company, employee, other = web_case
    employee.admission_date = date(2024, 1, 1)
    db.add(EmployeeComplianceProfile(employee_id=employee.id, salary_type="Mensual"))
    lines = []
    for i, month in enumerate(range(5, 11)):
        payroll = Payroll(company_id=company.id, period=f"2025-{month:02d}", status="Cerrada",
                          closed_at=datetime(2025, 11, 3, 12, tzinfo=UTC))
        db.add(payroll); db.flush()
        gross = 3_380_000 + i * 100_000 + int(i == 0)
        line = PayrollLine(payroll_id=payroll.id, employee_id=employee.id, base_salary=3_000_000+i*100_000,
                           overtime=100_000+int(i == 0), commissions=200_000, bonuses=50_000, other_income=30_000,
                           absences_discount=20_000, advances=100_000, other_discount=20_000,
                           ips_employee=0, gross=gross, total_discounts=140_000, net=gross-140_000)
        db.add(line); db.flush()
        db.add(PayrollComplianceDetail(payroll_line_id=line.id, period_start=date(2025,month,1),
                                      period_end=date(2025,month,monthrange(2025,month)[1])))
        lines.append(line)
    db.commit()
    yield client, db, box, company, employee, other, lines


def proposal(case, **params):
    client, _db, _box, company, employee, *_ = case
    response = client.get('/api/liquidaciones/promedio-salarial', params={
        'company_id':company.id, 'employee_id':employee.id, 'end_date':'2025-10-31', **params})
    assert response.status_code == 200, response.text
    return response.json()


def selected_inputs(case):
    client, _db, _box, company, employee, *_ = case
    data = proposal(case)
    return settlement_data(
        start_date=employee.admission_date.isoformat(), end_date='2025-10-31',
        company_id=str(company.id), employee_id=str(employee.id),
        average_origin='payroll', average_payroll_reviewed='on',
        average_payroll_fingerprint=data['fingerprint'], average_salary=data['average_salary'],
        csrf_token=token(client),
    )


def test_six_calendar_months_use_recorded_components_and_subtract_only_absences(average_case):
    result = proposal(average_case)
    assert result['is_available']
    assert (result['window_start'],result['window_end']) == ('2025-05-01','2025-10-31')
    assert result['closed_count'] == result['expected_count'] == 6
    assert result['recorded_total'] == 21_660_001
    assert result['average_salary'] == '3610000.17'
    assert result['periods'][0]['gross'] == 3_380_001
    assert result['periods'][0]['remuneration'] == 3_360_001
    assert len(result['fingerprint']) == 64


@pytest.mark.parametrize('change,status',[
    ('missing','Sin nómina'), ('open','Nómina no cerrada'),
    ('invalid','Importes inconsistentes'), ('no_date','Falta constancia de cierre'),
    ('partial_detail','Fechas del período incompletas o parciales'),
    ('bad_ips','Importes inconsistentes'),
])
def test_incomplete_or_inconsistent_sources_never_produce_an_average(average_case,change,status):
    _client, db, _box, _company, _employee, _other, lines = average_case
    line = lines[0]
    if change == 'missing':
        db.delete(db.scalar(select(PayrollComplianceDetail).where(PayrollComplianceDetail.payroll_line_id==line.id)))
        db.delete(line)
    elif change == 'open': line.payroll.status='En revisión'
    elif change == 'invalid': line.gross += 1
    elif change == 'no_date': line.payroll.closed_at=None
    elif change == 'partial_detail':
        db.scalar(select(PayrollComplianceDetail).where(PayrollComplianceDetail.payroll_line_id==line.id)).period_start=date(2025,5,2)
    elif change == 'bad_ips': line.ips_base=3_000_000;line.ips_rate=9
    db.commit()
    result=proposal(average_case)
    assert result['average_salary'] is None and not result['is_available'] and result['fingerprint'] is None
    assert result['periods'][0]['status']==status
    assert result['periods'][0]['remuneration'] is None


@pytest.mark.parametrize('salary_type',['Jornal','No especificado','Quincenal'])
def test_monthly_modality_must_be_explicit(average_case,salary_type):
    _client,db,_box,_company,employee,*_=average_case
    db.scalar(select(EmployeeComplianceProfile).where(EmployeeComplianceProfile.employee_id==employee.id)).salary_type=salary_type
    db.commit()
    result=proposal(average_case)
    assert result['closed_count']==6 and result['average_salary'] is None
    assert any('tipo de salario' in message for message in result['blockers'])


def test_less_than_six_months_only_applies_to_actual_shorter_service(average_case):
    _client,db,_box,_company,employee,*_=average_case
    employee.admission_date=date(2025,8,1);db.commit()
    result=proposal(average_case)
    assert result['is_available'] and result['expected_count']==3
    assert result['average_salary']=='3760000.00'
    assert [r['period'] for r in result['periods']]==['2025-08','2025-09','2025-10']


def test_partial_windows_and_mismatched_hire_dates_are_explicitly_unavailable(average_case):
    _client,db,_box,_company,employee,*_=average_case
    partial=propose_monthly_average(db,employee,date(2025,10,15))
    assert not partial['is_available'] and partial['average_salary'] is None
    assert partial['window_start']=='2025-04-16' and len(partial['periods'])==7
    assert any('fracciones' in message for message in partial['blockers'])
    mismatched=propose_monthly_average(db,employee,date(2025,10,31),start=date(2024,2,1))
    assert not mismatched['is_available']
    assert any('ingreso difiere' in message for message in mismatched['blockers'])


def test_future_and_different_recorded_exit_require_review(average_case):
    _client,db,_box,_company,employee,*_=average_case
    future=propose_monthly_average(db,employee,date(2025,10,31),today=date(2025,9,1))
    assert any('futura' in message for message in future['blockers'])
    employee.termination_date=date(2025,9,30);db.commit()
    assert any('egreso difiere' in message for message in proposal(average_case)['blockers'])


def test_no_salary_fallback_and_zero_remuneration_is_not_a_positive_average(average_case):
    _client,db,_box,_company,employee,_other,lines=average_case
    for line in lines:
        for key in ('base_salary','overtime','commissions','bonuses','other_income','absences_discount','advances','other_discount','ips_employee','gross','total_discounts','net'):
            setattr(line,key,0)
    employee.base_salary=8_000_000;db.commit()
    result=proposal(average_case)
    assert not result['is_available'] and result['average_salary'] is None
    for line in lines: line.payroll.status='Borrador'
    db.commit()
    result=proposal(average_case)
    assert result['closed_count']==0 and result['recorded_total']==0 and result['average_salary'] is None


def test_tenant_scope_and_headers(average_case):
    client,_db,_box,company,employee,other,_lines=average_case
    for ids in [(other.company_id,other.id),(company.id,other.id)]:
        response=client.get('/api/liquidaciones/promedio-salarial',params=dict(company_id=ids[0],employee_id=ids[1],end_date='2025-10-31'))
        assert response.status_code==404
    response=client.get('/api/liquidaciones/promedio-salarial',params=dict(company_id=company.id,employee_id=employee.id,end_date='2025-10-31'))
    assert 'no-store' in response.headers['cache-control']
    assert 'document_number' not in response.text and 'full_name' not in response.text


def test_average_endpoint_requires_authentication():
    with TestClient(core.app) as client:
        response=client.get('/api/liquidaciones/promedio-salarial?company_id=1&employee_id=1&end_date=2025-10-31',follow_redirects=False)
        assert response.status_code in {302,303,307,401,403}


@pytest.mark.parametrize('overrides,field',[
    ({'average_payroll_reviewed':''},'average_payroll_reviewed'),
    ({'average_payroll_fingerprint':'forged'},'average_salary'),
    ({'average_salary':'9999999'},'average_salary'),
])
def test_applying_requires_review_unchanged_sources_and_the_proposed_amount(average_case,overrides,field):
    _client,db,_box,_company,employee,*_=average_case
    values=selected_inputs(average_case);values.update(overrides)
    with pytest.raises(CalculationError) as error:
        verify_average_selection(db,employee,values)
    assert error.value.field==field


def test_preview_calculation_save_copy_and_pdf_preserve_the_actual_sources(average_case):
    client,db,_box,company,employee,*_=average_case
    page=client.get(f'/app/liquidaciones?tipo=settlement&company_id={company.id}&employee_id={employee.id}')
    assert 'Promedio desde nóminas' in page.text and 'payroll-average.js?v=' in page.text
    assert 'data-average-apply disabled' in page.text
    values=selected_inputs(average_case)
    calculated=client.post('/app/liquidaciones/calcular',data=values)
    assert calculated.status_code==200
    assert 'Nóminas cerradas; conceptos revisados' in calculated.text
    saved=client.post('/app/liquidaciones/guardar',data=values,follow_redirects=False)
    assert saved.status_code==303
    record=db.scalar(select(CalculationRecord).where(CalculationRecord.employee_id==employee.id))
    result=json.loads(record.result_json)
    assert result['average_provenance']['average_salary']=='3610000.17'
    assert result['average_provenance']['closed_count']==6
    assert json.loads(record.input_json)['average_origin']=='payroll'
    core._revalidate_calculation_before_approval(record,db)
    copied=client.get(f'/app/liquidaciones/{record.id}/copiar')
    assert 'name="average_origin" value="payroll"' in copied.text
    pdf=client.get(f'/app/liquidaciones/{record.id}/exportar/pdf')
    text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert '2025-05' in text and '2025-10' in text and 'Nóminas cerradas' in text


def test_changed_payroll_or_tampered_snapshot_blocks_approval_and_new_exports(average_case):
    client,db,_box,_company,employee,_other,lines=average_case
    values=selected_inputs(average_case)
    saved=client.post('/app/liquidaciones/guardar',data=values,follow_redirects=False)
    assert saved.status_code==303
    record=db.scalar(select(CalculationRecord).where(CalculationRecord.employee_id==employee.id))
    old=record.result_json
    result=json.loads(old);result['average_provenance']['periods'][0]['gross']+=1
    record.result_json=json.dumps(result)
    with pytest.raises(HTTPException) as error: core._revalidate_calculation_before_approval(record,db)
    assert error.value.status_code==409
    record.result_json=old
    lines[0].payroll.status='Borrador';db.commit()
    with pytest.raises(HTTPException): core._revalidate_calculation_before_approval(record,db)
    for path in ['/app/liquidaciones/calcular','/app/liquidaciones/exportar/csv','/app/liquidaciones/guardar']:
        response=client.post(path,data=values)
        assert response.status_code==422 and 'No se puede aplicar el promedio' in response.text
    assert json.loads(record.result_json)==json.loads(old)


def test_json_create_and_replace_validate_average_sources(average_case):
    client,db,_box,_company,employee,*_=average_case
    values=selected_inputs(average_case)
    created=client.post('/api/calculations',json=values,headers={'X-CSRF-Token':values['csrf_token']})
    assert created.status_code==201,created.text
    record=db.scalar(select(CalculationRecord).where(CalculationRecord.employee_id==employee.id))
    values['average_payroll_reviewed']=''
    changed=client.put(f'/api/calculations/{record.id}',json=values,headers={'X-CSRF-Token':values['csrf_token']})
    assert changed.status_code==422
    assert json.loads(record.input_json)['average_payroll_reviewed']=='on'


def test_new_payroll_creation_and_closure_feed_the_proposal_without_extra_setup(web_case):
    client,db,_box,company,employee,*_=web_case
    employee.admission_date=date(2024,1,1)
    db.add(EmployeeComplianceProfile(employee_id=employee.id,salary_type='Mensual'));db.commit()
    csrf=token(client)
    for month in range(5,11):
        created=client.post('/app/payrolls',data=dict(csrf_token=csrf,company_id=company.id,period=f'2025-{month:02d}'),follow_redirects=False)
        assert created.status_code==303,created.text
        payroll_id=int(created.headers['location'].rsplit('/',1)[-1])
        closed=client.post(f'/app/payrolls/{payroll_id}/status',data=dict(csrf_token=csrf,status='Cerrada'),follow_redirects=False)
        assert closed.status_code==303,closed.text
    response=client.get('/api/liquidaciones/promedio-salarial',params=dict(company_id=company.id,employee_id=employee.id,end_date='2025-10-31'))
    assert response.status_code==200
    assert response.json()['is_available'],response.json()['blockers']
    assert response.json()['average_salary']=='3500000.00'
