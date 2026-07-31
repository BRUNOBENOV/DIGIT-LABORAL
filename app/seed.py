from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from .auth import hash_password
from .database import SessionLocal
from .models import Branch, Company, CompanyRequest, Employee, LaborArticle, LaborParameter, RequestEvent, RequestWorkflow, Studio, User
from .config import settings

SOURCE_213 = "https://www.bacn.gov.py/leyes-paraguayas/2608/ley-n-213-establece-el-codigo-del-trabajo"
SOURCE_496 = "https://www.bacn.gov.py/leyes-paraguayas/2514/ley-n-496-modifica-amplia-y-deroga-articulos-de-la-ley-21393-codigo-del-trabajo"
SOURCE_MINIMUM_2026 = "https://www.mtess.gov.py/?p=36371"
SOURCE_IPS = "https://portal.ips.gov.py/sistemas/ipsportal/contenido.php?c=69"

# Síntesis orientativas para búsqueda interna. Siempre se conserva el enlace a la fuente oficial.
ARTICLES = [
    ("1", "Objeto y aplicación", "Disposiciones generales", "Regula las relaciones entre trabajadores y empleadores derivadas de una actividad laboral subordinada y remunerada.", SOURCE_213, ""),
    ("3", "Irrenunciabilidad", "Principios laborales", "Los derechos laborales reconocidos legalmente no pueden ser renunciados o limitados por acuerdos particulares en perjuicio del trabajador.", SOURCE_213, ""),
    ("5", "Garantías mínimas", "Principios laborales", "Las garantías del Código constituyen un mínimo y deben considerarse las condiciones más favorables al trabajador.", SOURCE_213, ""),
    ("58", "Período de prueba", "Contrato de trabajo", "Regula el periodo inicial para valorar aptitudes y condiciones del vínculo, cuya extensión depende del tipo de trabajo.", SOURCE_213, ""),
    ("62", "Obligaciones del empleador", "Obligaciones y derechos", "Incluye deberes de ocupación, pago, provisión de medios, respeto, seguridad, higiene y expedición de constancias.", SOURCE_213, ""),
    ("63", "Prohibiciones al empleador", "Obligaciones y derechos", "Reúne conductas prohibidas al empleador, incluidas retenciones no autorizadas y prácticas contrarias a los derechos laborales.", SOURCE_213, ""),
    ("67", "Derechos del trabajador", "Obligaciones y derechos", "Reconoce derechos vinculados con remuneración, descansos, igualdad salarial, indemnizaciones y condiciones dignas.", SOURCE_213, ""),
    ("91", "Terminación del contrato", "Terminación laboral", "Enumera causas generales por las cuales puede finalizar el contrato de trabajo.", SOURCE_213, ""),
    ("154", "Descanso semanal", "Descansos y vacaciones", "Establece el descanso semanal obligatorio y reglas generales aplicables.", SOURCE_213, ""),
    ("218", "Concepto de salario", "Salarios", "Define el salario como la remuneración debida por el empleador en virtud del contrato de trabajo.", SOURCE_213, ""),
    ("243", "Salario mínimo", "Salarios", "Establece la finalidad protectora del salario mínimo y su relación con las necesidades normales del trabajador.", SOURCE_213, ""),
    ("182", "Jornada rural", "Jornada de trabajo", "Referencia la jornada ordinaria aplicable a actividades rurales conforme a la modificación legal correspondiente.", SOURCE_496, "Modificado por Ley N.º 496/95"),
]

PARAMETERS = [
    ("minimum_monthly_salary_general", "Salario mínimo mensual general", Decimal("3044000"), "Gs.", date(2026, 7, 1), SOURCE_MINIMUM_2026, "Actividades diversas no especificadas."),
    ("minimum_daily_wage_general", "Jornal mínimo general", Decimal("117077"), "Gs.", date(2026, 7, 1), SOURCE_MINIMUM_2026, "Referencia general publicada por el MTESS."),
    ("minimum_hourly_wage_general", "Valor hora diurna general", Decimal("12683"), "Gs.", date(2026, 7, 1), SOURCE_MINIMUM_2026, "Referencia general para jornada diurna."),
    ("ips_employee_rate_general", "Aporte IPS del trabajador — régimen general", Decimal("9"), "%", date(2026, 1, 1), SOURCE_IPS, "Parámetro general; verificar regímenes especiales."),
    ("ips_employer_rate_general", "Aporte IPS del empleador — régimen general", Decimal("16.5"), "%", date(2026, 1, 1), SOURCE_IPS, "Parámetro general; verificar regímenes especiales."),
]


def seed_database() -> None:
    """Create reference data and, when configured, a protected first admin account.

    Passwords are read from environment variables and are never committed to the
    public repository. Demo business records can be disabled with
    ``SEED_DEMO_DATA=false``.
    """
    with SessionLocal() as db:
        if settings.system_admin_email and settings.system_admin_password:
            if db.scalar(select(User.id).where(User.role == "superadmin")) is None:
                db.add(
                    User(
                        full_name="Administrador General",
                        email=settings.system_admin_email,
                        password_hash=hash_password(settings.system_admin_password),
                        role="superadmin",
                        must_change_password=False,
                    )
                )

        studio = db.scalar(select(Studio).order_by(Studio.id).limit(1))
        if studio is None and settings.seed_demo_data:
            studio = Studio(
                name="Victor's Contabilidad",
                phone="0983 102 220",
                plan_name="Profesional",
                company_limit=15,
                payment_status="Activo",
            )
            db.add(studio)
            db.flush()

            companies = [
                Company(studio_id=studio.id, legal_name="Comercial Paraná S.A.", trade_name="Comercial Paraná", ruc="80123456-7", city="Ciudad del Este", address="Av. Demo 123", phone="0981 555 100", email="administracion@parana.demo", legal_representative="María López", ips_employer_number="IPS-102", mtess_employer_number="MTESS-102", responsible_name="Equipo Laboral", status="Activa"),
                Company(studio_id=studio.id, legal_name="Servicios del Este S.R.L.", trade_name="Servicios del Este", ruc="80076543-2", city="Hernandarias", phone="0973 444 220", email="rrhh@servicios.demo", legal_representative="Juan González", ips_employer_number="IPS-245", responsible_name="Equipo Laboral", status="Pendiente"),
                Company(studio_id=studio.id, legal_name="Distribuidora Central E.A.S.", trade_name="Distri Central", ruc="80111111-3", city="Minga Guazú", phone="0984 555 240", responsible_name="Equipo Laboral", status="Activa"),
            ]
            db.add_all(companies)
            db.flush()
            db.add_all([
                Branch(company_id=companies[0].id, name="Casa central", city="Ciudad del Este", address="Av. Demo 123"),
                Branch(company_id=companies[0].id, name="Sucursal km 7", city="Ciudad del Este", address="Ruta PY02"),
                Branch(company_id=companies[1].id, name="Casa central", city="Hernandarias"),
                Branch(company_id=companies[2].id, name="Casa central", city="Minga Guazú"),
            ])
            db.add_all([
                Employee(company_id=companies[0].id, full_name="Juan Pérez González", document_number="3.450.123", position="Vendedor", admission_date=date(2024, 2, 1), base_salary=3_044_000, ips_contributor=True),
                Employee(company_id=companies[0].id, full_name="María López Benítez", document_number="4.120.987", position="Encargada", admission_date=date(2023, 8, 15), base_salary=4_500_000, ips_contributor=True),
                Employee(company_id=companies[1].id, full_name="Pedro Fernández", document_number="5.231.880", position="Auxiliar", admission_date=date(2025, 1, 10), base_salary=3_150_000, ips_contributor=True),
                Employee(company_id=companies[1].id, full_name="Ana Duarte", document_number="4.990.021", position="Administrativa", admission_date=date(2024, 6, 3), base_salary=3_800_000, ips_contributor=True),
            ])
            db.add_all([
                CompanyRequest(company_id=companies[0].id, request_type="Alta de funcionario", subject="Ingreso de nuevo vendedor", detail="Solicitamos registrar a un nuevo vendedor desde el 1 de agosto.", priority="Alta", status="Pendiente"),
                CompanyRequest(company_id=companies[1].id, request_type="Cambio salarial", subject="Propuesta de aumento", detail="Revisar aumento propuesto para la funcionaria administrativa.", status="En revisión"),
            ])

        if studio and settings.admin_email and settings.admin_password:
            existing_admin = db.scalar(select(User.id).where(User.email == settings.admin_email))
            if existing_admin is None:
                db.add(
                    User(
                        studio_id=studio.id,
                        full_name="Administrador del estudio",
                        email=settings.admin_email,
                        password_hash=hash_password(settings.admin_password),
                        role="administrador",
                        must_change_password=False,
                    )
                )

        if db.scalar(select(LaborArticle.id).limit(1)) is None:
            db.add_all([
                LaborArticle(article_number=n, heading=h, category=c, body=b, source_url=s, amendment_note=a, reviewed_at=date(2026, 7, 30))
                for n, h, c, b, s, a in ARTICLES
            ])

        for key, label, value, unit, effective, source, notes in PARAMETERS:
            if db.scalar(select(LaborParameter.id).where(LaborParameter.key == key)) is None:
                db.add(LaborParameter(key=key, label=label, value=value, unit=unit, effective_from=effective, source_url=source, notes=notes))

        # Backfill the v13 workflow for requests created by earlier versions.
        for request_item in db.scalars(select(CompanyRequest)):
            if request_item.workflow is None:
                db.add(RequestWorkflow(request_id=request_item.id, requested_by="Versión anterior", payload_json="{}"))
                db.add(RequestEvent(request_id=request_item.id, event_type="Importación", status=request_item.status, note="Solicitud incorporada al nuevo flujo de seguimiento.", user_email="sistema"))

        db.commit()
