from datetime import date, timedelta
from pathlib import Path
import re
import uuid

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Company, Employee, User


def test_direction_orders_all_filtered_employees_before_pagination_and_report_export():
    company_id = None
    with TestClient(app) as client:
        login = client.get('/login')
        token = re.search(r'name="csrf_token" value="([^"]+)"', login.text).group(1)
        response = client.post('/login', data={'email':'admin@digitlaboral.com.py','password':settings.demo_admin_password,'csrf_token':token}, follow_redirects=False)
        assert response.status_code == 303
        suffix = uuid.uuid4().hex[:12]
        with SessionLocal() as db:
            studio = db.scalar(select(User.studio_id).where(User.email=='admin@digitlaboral.com.py'))
            company = Company(studio_id=studio,company_code=int(uuid.uuid4().int%1_000_000_000)+1,legal_name='Sort QA '+suffix,ruc='QA-'+suffix,status='Activa')
            db.add(company)
            db.flush()
            company_id=company.id
            db.add_all([Employee(company_id=company_id,employee_code=index+1,full_name=f'Sort QA {104-index:03d}',document_number=f'QA-{suffix}-{index}',position='Auxiliar',admission_date=date(2020,1,1)+timedelta(days=index),base_salary=1_000_000+index*1000,status='Desvinculado') for index in range(105)])
            db.commit()
        try:
            filters={'company_id':company_id,'q':'Sort QA','status_filter':'Desvinculado','show_archived':'true','employee_sort':'code','direction':'desc','employee_quick':'all'}
            def codes(response):
                assert response.status_code==200
                return [int(row['data-employee-code']) for row in BeautifulSoup(response.text,'html.parser').select('tr[data-employee-row]')]
            first=client.get('/app/employees',params=filters)
            second=client.get('/app/employees',params={**filters,'page':2})
            assert codes(first)==list(range(105,5,-1))
            assert codes(second)==list(range(5,0,-1))
            assert 'direction=desc' in first.text and 'employee_sort=code' in first.text
            assert 'data-sort-direction="desc"' in first.text
            assert 'status_filter=Desvinculado' in first.text and 'employee_quick=all' in first.text
            asc=client.get('/app/employees',params={**filters,'direction':'asc'})
            assert codes(asc)==list(range(1,101))
            filtered=client.get('/app/employees',params={**filters,'q':'Sort QA 000'})
            assert codes(filtered)==[105]
            for sort,expected in [('salary',1_000_000),('-salary',1_104_000)]:
                report=client.get('/api/reports/listado-empleado',params={'company_id':company_id,'q':'Sort QA','sort':sort,'page_size':100})
                assert report.status_code==200
                data=report.json()
                assert data['total']==105
                assert data['records'][0]['Salario base (Gs.)']==expected
            html=client.get('/app/reports/listado-empleado',params={'company_id':company_id,'q':'Sort QA','sort':'-salary'})
            assert html.status_code==200
            assert 'data-sort-signed' in html.text and 'data-sort-direction="desc"' in html.text
            assert 'sort=-salary' in html.text
        finally:
            with SessionLocal() as db:
                for employee in db.scalars(select(Employee).where(Employee.company_id==company_id)).all():db.delete(employee)
                company=db.get(Company,company_id)
                if company:db.delete(company)
                db.commit()


def test_shared_direction_assets_load_before_the_list_enhancements():
    root=Path(__file__).resolve().parents[1]
    base=(root/'app/templates/base.html').read_text()
    assert base.index("path='sort-controls.js'") < base.index("path='maintenance-workspace-263.js'")
    assert 'sort-controls.css' in base
