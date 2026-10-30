from __future__ import annotations

import io
import json
import uuid

from PIL import Image
from sqlalchemy import func, select

from .database import SessionLocal
from .main import ruc_check_digit
from .models import CalculationRecord, Company, Employee, Payroll, PayrollLine, User, Vacation
from .persona_qa_http import expect_status, login, logout


def _image_bytes(fmt: str, size=(700, 220)) -> bytes:
    mode = 'RGBA' if fmt == 'PNG' else 'RGB'
    fill = (40, 90, 170, 255) if mode == 'RGBA' else (40, 90, 170)
    image = Image.new(mode, size, fill)
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def run_admin_workflow(check, client, password: str) -> dict:  # noqa: ANN001
    login(check, client, 'admin@digitlaboral.com.py', password)
    for path in ('/app', '/app/companies', '/app/employees', '/app/payrolls', '/app/calculations', '/app/vacations', '/app/compliance', '/app/documents', '/app/reports', '/app/calendar', '/app/labor-code', '/app/users', '/app/audit'):
        expect_status(check, client.get(path), {200}, f'admin GET {path}')

    bad_company = client.post('/app/companies', data={'legal_name': '', 'ruc': 'x'}, follow_redirects=False)
    expect_status(check, bad_company, {303}, 'validación empresa vacía')
    check('form_error=' in bad_company.headers.get('location', ''), 'empresa inválida sin mensaje claro')

    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.email == 'admin@digitlaboral.com.py'))
        check(admin is not None and admin.studio_id is not None, 'admin QA sin estudio asociado')
        studio_id = admin.studio_id if admin and admin.studio_id is not None else 0
        next_company_code = (db.scalar(
            select(func.max(Company.company_code)).where(Company.studio_id == studio_id)
        ) or 0) + 1
    # QA uses a unique syntactically valid RUC so repeated CI runs cannot collide with seeded fixtures.
    ruc_base = str(81_000_000 + uuid.uuid4().int % 999_999)
    company_ruc = f'{ruc_base}-{ruc_check_digit(ruc_base)}'
    company_payload = {
        'company_code': str(next_company_code),
        'legal_name': 'QA Empresa Profesional S.A.', 'trade_name': 'QA Profesional', 'ruc': company_ruc,
        'owner_name': 'Propietario QA',
        'city': 'Ciudad del Este', 'department': 'Alto Paraná',
        'address': 'Ruta QA 100', 'phone': '0981000000', 'email': 'qa@empresa.test',
        'legal_representative': 'Representante QA', 'legal_representative_document': '1234567',
        'ips_employer_number': '123456', 'mtess_employer_number': '654321',
        'work_sector': 'Administración', 'work_location': 'Casa central',
        'economic_activity': 'Servicios profesionales',
        'contact_name': 'Contacto QA', 'responsible_name': 'Contador QA',
    }
    response = client.post('/api/companies', json=company_payload, headers={'Accept': 'application/json'})
    if response.status_code != 201:
        raise RuntimeError(
            f"QA no pudo crear la empresa por API: HTTP {response.status_code}; respuesta={response.text[:1000]}"
        )
    company_id = int(response.json()['id'])
    with SessionLocal() as db:
        company = db.get(Company, company_id)
        if company is None:
            raise RuntimeError("QA API devolvió un ID de empresa que no existe en la base")

    for fmt, mime, ext in (('PNG', 'image/png', 'png'), ('JPEG', 'image/jpeg', 'jpg'), ('WEBP', 'image/webp', 'webp')):
        response = client.post(f'/app/companies/{company_id}/logo', files={'logo': (f'logo.{ext}', _image_bytes(fmt), mime)}, follow_redirects=False)
        expect_status(check, response, {303}, f'subir logo {fmt}')
        check('logo_saved=1' in response.headers.get('location', ''), f'logo {fmt} no confirma guardado')
    response = client.post(f'/app/companies/{company_id}/logo', files={'logo': ('falso.png', b'no-es-imagen', 'image/png')}, follow_redirects=False)
    expect_status(check, response, {303}, 'logo inválido')
    check('logo_error=' in response.headers.get('location', ''), 'logo inválido sin feedback')

    invalid_employee = {
        'company_id': str(company_id), 'full_name': 'Persona Fecha Inválida', 'document_number': '9000001',
        'birth_date': '2026-10-01', 'position': 'Analista', 'admission_date': '2026-09-01', 'contract_type': 'Tiempo indefinido',
        'payment_frequency': 'Mensual', 'base_salary': '3500000', 'ips_contributor': 'on',
    }
    response = client.post('/app/employees', data=invalid_employee, follow_redirects=False)
    expect_status(check, response, {303}, 'validación fechas funcionario')
    check('form_error=' in response.headers.get('location', ''), 'fecha inválida funcionario sin feedback')

    employee_payload = {
        'company_id': str(company_id), 'full_name': 'Persona QA Laboral', 'document_number': '9000002',
        'birth_date': '1995-05-05', 'position': 'Analista', 'admission_date': '2020-02-10', 'contract_type': 'Tiempo indefinido',
        'payment_frequency': 'Mensual', 'base_salary': '4200000', 'email': 'persona@qa.test', 'phone': '0981111111',
        'address': 'CDE', 'ips_contributor': 'on', 'notes': 'Alta por QA',
    }
    response = client.post('/app/employees', data=employee_payload, follow_redirects=False)
    expect_status(check, response, {303}, 'crear funcionario')
    with SessionLocal() as db:
        employee = db.scalar(select(Employee).where(Employee.company_id == company_id, Employee.document_number == '9000002'))
        check(employee is not None, 'funcionario QA no persistió')
        employee_id = employee.id if employee else 0

    response = client.post('/app/vacations', data={'employee_id': str(employee_id), 'period_year': '2026', 'entitled_days': '12', 'used_days': '13', 'status': 'Pendiente'}, follow_redirects=False)
    expect_status(check, response, {303}, 'vacaciones uso mayor al concedido')
    check('form_error=' in response.headers.get('location', ''), 'vacaciones inconsistentes sin feedback')

    response = client.post('/app/vacations', data={'employee_id': str(employee_id), 'period_year': '2026', 'entitled_days': '', 'used_days': '0', 'status': 'Aprobada', 'start_date': '2026-10-01', 'end_date': '2026-10-18', 'notes': 'QA'}, follow_redirects=False)
    expect_status(check, response, {303}, 'crear vacaciones con referencia automática')
    with SessionLocal() as db:
        vacation = db.scalar(select(Vacation).where(Vacation.employee_id == employee_id).order_by(Vacation.id.desc()))
        check(vacation is not None and vacation.entitled_days == 18, f'referencia vacaciones esperada 18, obtenida {getattr(vacation, "entitled_days", None)}')

    response = client.post('/app/calculations', data={
        'calculation_type': 'salary', 'company_id': str(company_id), 'employee_id': str(employee_id), 'reference_period': '2026-09',
        'gross': '4200000', 'other_income': '600000', 'ips_base': '4200000', 'other_discount': '100000', 'apply_ips': 'on', 'notes': 'Base IPS revisada',
    }, follow_redirects=False)
    expect_status(check, response, {303}, 'guardar cálculo salario')
    with SessionLocal() as db:
        calc = db.scalar(select(CalculationRecord).where(CalculationRecord.company_id == company_id, CalculationRecord.calculation_type == 'salary').order_by(CalculationRecord.id.desc()))
        check(calc is not None, 'cálculo salarial no persistió')
        if calc:
            inputs = json.loads(calc.input_json); results = json.loads(calc.result_json)
            check(inputs.get('ips_base') == 4_200_000, 'base IPS del cálculo no quedó registrada')
            check(results.get('ips_employee') == 378_000, f'IPS esperado 378000, obtenido {results.get("ips_employee")}')
            check(calc.status == 'Revisar', 'cálculo nuevo no queda en Revisar')

    response = client.post('/app/calculations', data={'calculation_type': 'vacation', 'company_id': str(company_id), 'employee_id': str(employee_id), 'reference_period': '2026', 'salary': '2000000', 'days': '12', 'notes': 'QA mínimo'}, follow_redirects=False)
    expect_status(check, response, {303}, 'guardar cálculo vacaciones')
    with SessionLocal() as db:
        calc = db.scalar(select(CalculationRecord).where(CalculationRecord.company_id == company_id, CalculationRecord.calculation_type == 'vacation').order_by(CalculationRecord.id.desc()))
        check(calc is not None, 'cálculo vacaciones no persistió')
        if calc:
            results = json.loads(calc.result_json)
            check(results.get('base_monthly') == 3_044_000, f'vacaciones no aplicó referencia mínima: {results.get("base_monthly")}')

    response = client.post('/app/payrolls', data={'company_id': str(company_id), 'period': '2026-09', 'notes': 'QA'}, follow_redirects=False)
    expect_status(check, response, {303}, 'crear liquidación')
    with SessionLocal() as db:
        payroll = db.scalar(select(Payroll).where(Payroll.company_id == company_id, Payroll.period == '2026-09'))
        check(payroll is not None, 'liquidación QA no persistió')
        payroll_id = payroll.id if payroll else 0
        line = db.scalar(select(PayrollLine).where(PayrollLine.payroll_id == payroll_id, PayrollLine.employee_id == employee_id))
        check(line is not None, 'línea de liquidación QA ausente')
        line_id = line.id if line else 0

    response = client.post(f'/app/payrolls/{payroll_id}/lines/{line_id}', data={'base_salary': '4200000', 'overtime': '300000', 'commissions': '200000', 'bonuses': '100000', 'other_income': '200000', 'ips_base': '4200000', 'absences_discount': '0', 'advances': '100000', 'other_discount': '50000', 'ips_basis_note': 'Base revisada en caso QA', 'other_discount_note': 'Descuento documentado de ejemplo', 'ips_rate': '9', 'days_worked': '22'}, follow_redirects=False)
    expect_status(check, response, {303}, 'editar línea con base IPS')
    with SessionLocal() as db:
        line = db.get(PayrollLine, line_id)
        check(line is not None and line.gross == 5_000_000, f'bruto inesperado {getattr(line, "gross", None)}')
        check(line is not None and line.ips_employee == 378_000, f'IPS no respetó base: {getattr(line, "ips_employee", None)}')
        check(line is not None and line.ips_base == 4_200_000, 'base IPS no persistió')
        check(line is not None and float(line.ips_rate) == 9, 'tasa histórica IPS no persistió')
    receipt = client.get(f'/app/payrolls/{payroll_id}/recibos.pdf?line_id={line_id}')
    expect_status(check, receipt, {200}, 'descarga recibo PDF con sesión real')
    check(receipt.content.startswith(b'%PDF'), 'recibo no contiene PDF')
    expect_status(check, client.get('/herramientas'), {200}, 'centro público')
    expect_status(check, client.get(f'/app/liquidaciones?company_id={company_id}&employee_id={employee_id}'), {200}, 'centro profesional contextual')

    # Direct status changes are forbidden. Validate the dedicated exit workflow
    # without modifying the live employee in the persona smoke scenario.
    legacy = client.post(f'/app/employees/{employee_id}/status', data={'status': 'Desvinculado', 'termination_date': '2019-01-01'}, follow_redirects=False)
    expect_status(check, legacy, {410}, 'estado directo retirado')
    response = client.post(
        f'/app/employees/{employee_id}/exit',
        data={'effective_date': '2019-01-01', 'reason': 'dismissal', 'initiated_by': 'Empleador'},
        follow_redirects=False,
    )
    expect_status(check, response, {422}, 'validación fecha de egreso en flujo dedicado')
    check('La fecha de egreso no puede anteceder' in response.text, 'egreso anterior al ingreso no rechazado con detalle')
    logout(check, client)
    return {'company_id': company_id, 'employee_id': employee_id, 'payroll_id': payroll_id, 'line_id': line_id}
