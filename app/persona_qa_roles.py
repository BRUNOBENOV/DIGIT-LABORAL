from __future__ import annotations

from sqlalchemy import select

from .database import SessionLocal
from .models import Company, LaborArticle, User
from .persona_qa_http import expect_status, login, logout


def run_role_and_legal_checks(check, client, password: str, context: dict) -> None:  # noqa: ANN001
    # Accountant persona: operational tools but no user administration.
    login(check, client, 'contador@demo.py', password)
    for path in ('/app', '/app/companies', '/app/employees', '/app/payrolls', '/app/calculations', '/app/compliance', '/app/labor-code'):
        expect_status(check, client.get(path), {200}, f'contador GET {path}')
    expect_status(check, client.get('/app/users'), {403}, 'contador no administra usuarios')
    logout(check, client)

    # Auxiliary persona: daily records, no master company creation.
    login(check, client, 'auxiliar@demo.py', password)
    expect_status(check, client.get('/app'), {200}, 'auxiliar dashboard')
    expect_status(check, client.get('/app/employees'), {200}, 'auxiliar funcionarios')
    response = client.post('/app/companies', data={'legal_name': 'No Permitida', 'ruc': '80000000-0'}, follow_redirects=False)
    expect_status(check, response, {403}, 'auxiliar no crea empresa')
    logout(check, client)

    # Business owner persona: only its tenant/company and simple navigation.
    login(check, client, 'empresa@demo.py', password)
    home = client.get('/app')
    expect_status(check, home, {200}, 'empresa dashboard')
    check('Tu empresa, sin vueltas' in home.text, 'dashboard empresa no está adaptado')
    check('Usuarios y permisos' not in home.text, 'empresa ve usuarios y permisos')
    check('Liquidaciones mensuales' not in home.text, 'empresa ve controles internos en inicio')
    for path in ('/app/companies', '/app/employees', '/app/documents', '/app/requests', '/app/labor-code'):
        expect_status(check, client.get(path), {200}, f'empresa GET {path}')
    with SessionLocal() as db:
        owner = db.scalar(select(User).where(User.email == 'empresa@demo.py'))
        check(owner is not None and owner.company_id is not None, 'usuario empresa demo no tiene empresa')
        own_id = owner.company_id if owner and owner.company_id else 0
        other = db.scalar(select(Company).where(Company.id != own_id).order_by(Company.id))
        check(other is not None, 'falta segunda empresa para prueba de aislamiento')
        other_id = other.id if other else 0
    expect_status(check, client.get(f'/app/companies/{own_id}'), {200}, 'empresa abre su expediente')
    expect_status(check, client.get(f'/app/companies/{other_id}'), {404}, 'empresa no abre otra empresa')
    response = client.post(f'/app/payrolls/{context["payroll_id"]}/lines/{context["line_id"]}', data={'base_salary': '1'}, follow_redirects=False)
    expect_status(check, response, {403}, 'empresa no edita liquidación')
    logout(check, client)

    # Lawyer persona: legal library critical mappings and document-related pages.
    login(check, client, 'admin@digitlaboral.com.py', password)
    with SessionLocal() as db:
        rows = list(db.scalars(select(LaborArticle).where(LaborArticle.article_number.in_(['154', '213', '218', '227', '243', '255']))))
        articles = {item.article_number: item for item in rows}
        check('213' in articles and 'descanso' in articles['213'].heading.lower(), 'art. 213 descanso semanal ausente')
        check('218' in articles and 'vacaciones' in articles['218'].heading.lower(), 'art. 218 no identifica vacaciones')
        check('227' in articles and 'salario' in articles['227'].heading.lower(), 'art. 227 concepto de salario ausente')
        check('243' in articles and 'aguinaldo' in articles['243'].heading.lower(), 'art. 243 no identifica aguinaldo')
        check('255' in articles and 'salario mínimo' in articles['255'].heading.lower(), 'art. 255 mínimo ausente')
        check(not ('154' in articles and articles['154'].heading == 'Descanso semanal'), 'persiste mapeo jurídico erróneo art. 154')
    law_page = client.get('/app/labor-code?q=218')
    expect_status(check, law_page, {200}, 'biblioteca jurídica')
    check('218' in law_page.text, 'búsqueda jurídica 218 sin resultado visible')
    expect_status(check, client.get('/app/certificates'), {200}, 'generador documentos jurídico-laborales')
    logout(check, client)
