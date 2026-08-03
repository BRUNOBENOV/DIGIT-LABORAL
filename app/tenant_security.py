from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from .config import settings

DIRECT_POLICIES = {
    "companies": "studio_id = digit_current_studio_id()",
    "audit_logs": "studio_id = digit_current_studio_id()",
    "security_events": "studio_id = digit_current_studio_id()",
    "studio_payments": "studio_id = digit_current_studio_id()",
    "integration_batches": "studio_id = digit_current_studio_id()",
}

COMPANY_POLICIES = {
    "branches": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "employees": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "company_requests": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "payrolls": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "documents": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "generated_certificates": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "company_branding": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "calculation_records": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "labor_deadlines": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "company_compliance_profiles": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "compliance_events": "company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
}

EMPLOYEE_POLICIES = {
    "vacations": "employee_id IN (SELECT e.id FROM employees e JOIN companies c ON c.id=e.company_id WHERE c.studio_id = digit_current_studio_id())",
    "aguinaldos": "employee_id IN (SELECT e.id FROM employees e JOIN companies c ON c.id=e.company_id WHERE c.studio_id = digit_current_studio_id())",
    "employee_events": "employee_id IN (SELECT e.id FROM employees e JOIN companies c ON c.id=e.company_id WHERE c.studio_id = digit_current_studio_id())",
    "salary_history": "employee_id IN (SELECT e.id FROM employees e JOIN companies c ON c.id=e.company_id WHERE c.studio_id = digit_current_studio_id())",
    "employee_compliance_profiles": "employee_id IN (SELECT e.id FROM employees e JOIN companies c ON c.id=e.company_id WHERE c.studio_id = digit_current_studio_id())",
}

REQUEST_POLICIES = {
    "request_workflows": "request_id IN (SELECT r.id FROM company_requests r JOIN companies c ON c.id=r.company_id WHERE c.studio_id = digit_current_studio_id())",
    "request_comments": "request_id IN (SELECT r.id FROM company_requests r JOIN companies c ON c.id=r.company_id WHERE c.studio_id = digit_current_studio_id())",
    "request_attachments": "request_id IN (SELECT r.id FROM company_requests r JOIN companies c ON c.id=r.company_id WHERE c.studio_id = digit_current_studio_id())",
}

OTHER_POLICIES = {
    "payroll_lines": "payroll_id IN (SELECT p.id FROM payrolls p JOIN companies c ON c.id=p.company_id WHERE c.studio_id = digit_current_studio_id())",
    "ai_interactions": "studio_id = digit_current_studio_id() OR company_id IN (SELECT id FROM companies WHERE studio_id = digit_current_studio_id())",
    "payroll_compliance_details": "payroll_line_id IN (SELECT pl.id FROM payroll_lines pl JOIN payrolls p ON p.id=pl.payroll_id JOIN companies c ON c.id=p.company_id WHERE c.studio_id = digit_current_studio_id())",
    "integration_batch_items": "batch_id IN (SELECT id FROM integration_batches WHERE studio_id = digit_current_studio_id())",
    "branch_compliance_profiles": "branch_id IN (SELECT b.id FROM branches b JOIN companies c ON c.id=b.company_id WHERE c.studio_id = digit_current_studio_id())",
}


def apply_postgres_rls(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    policies = {**DIRECT_POLICIES, **COMPANY_POLICIES, **EMPLOYEE_POLICIES, **REQUEST_POLICIES, **OTHER_POLICIES}
    existing_tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE OR REPLACE FUNCTION digit_current_studio_id() RETURNS BIGINT
            LANGUAGE SQL STABLE AS $$
                SELECT NULLIF(current_setting('app.current_studio_id', true), '')::BIGINT
            $$
        """))
        connection.execute(text("""
            CREATE OR REPLACE FUNCTION digit_is_superadmin() RETURNS BOOLEAN
            LANGUAGE SQL STABLE AS $$
                SELECT COALESCE(current_setting('app.is_superadmin', true), 'false') = 'true'
            $$
        """))
        for table, condition in policies.items():
            if table not in existing_tables:
                continue
            policy_name = f"digit_tenant_{table}"
            connection.exec_driver_sql(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            if settings.rls_force:
                connection.exec_driver_sql(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            else:
                connection.exec_driver_sql(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
            connection.exec_driver_sql(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table}"')
            combined = f"digit_is_superadmin() OR ({condition})"
            connection.exec_driver_sql(
                f'CREATE POLICY "{policy_name}" ON "{table}" FOR ALL USING ({combined}) WITH CHECK ({combined})'
            )


def rls_production_note() -> str:
    return (
        "RLS debe ejecutarse con un usuario PostgreSQL de aplicación que no sea propietario "
        "de las tablas ni tenga BYPASSRLS. RLS_FORCE solo debe activarse después de separar "
        "el usuario de migración del usuario de ejecución."
    )
