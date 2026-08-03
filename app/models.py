from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Studio(Base):
    __tablename__ = "studios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True)
    ruc: Mapped[str] = mapped_column(String(40), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    plan_name: Mapped[str] = mapped_column(String(80), default="Profesional")
    company_limit: Mapped[int] = mapped_column(Integer, default=15)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    payment_status: Mapped[str] = mapped_column(String(30), default="Activo")
    next_payment_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    users: Mapped[list["User"]] = relationship(back_populates="studio")
    companies: Mapped[list["Company"]] = relationship(back_populates="studio", cascade="all, delete-orphan")
    ai_interactions: Mapped[list["AIInteraction"]] = relationship(back_populates="studio", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    studio_id: Mapped[Optional[int]] = mapped_column(ForeignKey("studios.id"), nullable=True, index=True)
    company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(40), default="auxiliar")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    studio: Mapped[Optional[Studio]] = relationship(back_populates="users")
    company: Mapped[Optional["Company"]] = relationship(back_populates="users")


class ActivationRequest(Base):
    __tablename__ = "activation_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    studio_name: Mapped[str] = mapped_column(String(180))
    contact_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(180), index=True)
    phone: Mapped[str] = mapped_column(String(60), default="")
    estimated_companies: Mapped[int] = mapped_column(Integer, default=1)
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="Pendiente")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("studio_id", "ruc", name="uq_company_ruc_per_studio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    studio_id: Mapped[int] = mapped_column(ForeignKey("studios.id"), index=True)
    legal_name: Mapped[str] = mapped_column(String(200), index=True)
    trade_name: Mapped[str] = mapped_column(String(160), default="")
    ruc: Mapped[str] = mapped_column(String(40), index=True)
    city: Mapped[str] = mapped_column(String(100), default="Ciudad del Este")
    address: Mapped[str] = mapped_column(String(240), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(180), default="")
    legal_representative: Mapped[str] = mapped_column(String(180), default="")
    ips_employer_number: Mapped[str] = mapped_column(String(80), default="")
    mtess_employer_number: Mapped[str] = mapped_column(String(80), default="")
    responsible_name: Mapped[str] = mapped_column(String(160), default="Sin asignar")
    status: Mapped[str] = mapped_column(String(30), default="Activa")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    studio: Mapped[Studio] = relationship(back_populates="companies")
    branches: Mapped[list["Branch"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    employees: Mapped[list["Employee"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    requests: Mapped[list["CompanyRequest"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    users: Mapped[list[User]] = relationship(back_populates="company")
    payrolls: Mapped[list["Payroll"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    generated_certificates: Mapped[list["GeneratedCertificate"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    branding: Mapped[Optional["CompanyBranding"]] = relationship(back_populates="company", cascade="all, delete-orphan", uselist=False)
    calculations: Mapped[list["CalculationRecord"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    ai_interactions: Mapped[list["AIInteraction"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Branch(Base):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    city: Mapped[str] = mapped_column(String(100), default="")
    address: Mapped[str] = mapped_column(String(240), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    company: Mapped[Company] = relationship(back_populates="branches")


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("company_id", "document_number", name="uq_employee_document_per_company"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True)
    full_name: Mapped[str] = mapped_column(String(180), index=True)
    document_number: Mapped[str] = mapped_column(String(40), index=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    position: Mapped[str] = mapped_column(String(140), default="")
    admission_date: Mapped[date] = mapped_column(Date, default=date.today)
    contract_type: Mapped[str] = mapped_column(String(80), default="Tiempo indefinido")
    payment_frequency: Mapped[str] = mapped_column(String(40), default="Mensual")
    base_salary: Mapped[int] = mapped_column(Integer, default=0)
    ips_contributor: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[str] = mapped_column(String(180), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    address: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(30), default="Activo")
    termination_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    company: Mapped[Company] = relationship(back_populates="employees")
    branch: Mapped[Optional[Branch]] = relationship()
    payroll_lines: Mapped[list["PayrollLine"]] = relationship(back_populates="employee")
    generated_certificates: Mapped[list["GeneratedCertificate"]] = relationship(back_populates="employee")
    calculations: Mapped[list["CalculationRecord"]] = relationship(back_populates="employee")
    ai_interactions: Mapped[list["AIInteraction"]] = relationship(back_populates="employee")


class CompanyRequest(Base):
    __tablename__ = "company_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    request_type: Mapped[str] = mapped_column(String(100))
    subject: Mapped[str] = mapped_column(String(180), default="")
    detail: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(30), default="Normal")
    status: Mapped[str] = mapped_column(String(30), default="Pendiente")
    response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    company: Mapped[Company] = relationship(back_populates="requests")


class Payroll(Base):
    __tablename__ = "payrolls"
    __table_args__ = (UniqueConstraint("company_id", "period", name="uq_payroll_company_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    status: Mapped[str] = mapped_column(String(30), default="Borrador")
    notes: Mapped[str] = mapped_column(Text, default="")
    total_gross: Mapped[int] = mapped_column(Integer, default=0)
    total_ips_employee: Mapped[int] = mapped_column(Integer, default=0)
    total_discounts: Mapped[int] = mapped_column(Integer, default=0)
    total_net: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(180), default="")
    reviewed_by: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    company: Mapped[Company] = relationship(back_populates="payrolls")
    lines: Mapped[list["PayrollLine"]] = relationship(back_populates="payroll", cascade="all, delete-orphan")


class PayrollLine(Base):
    __tablename__ = "payroll_lines"
    __table_args__ = (UniqueConstraint("payroll_id", "employee_id", name="uq_payroll_employee"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payroll_id: Mapped[int] = mapped_column(ForeignKey("payrolls.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    base_salary: Mapped[int] = mapped_column(Integer, default=0)
    overtime: Mapped[int] = mapped_column(Integer, default=0)
    commissions: Mapped[int] = mapped_column(Integer, default=0)
    bonuses: Mapped[int] = mapped_column(Integer, default=0)
    other_income: Mapped[int] = mapped_column(Integer, default=0)
    absences_discount: Mapped[int] = mapped_column(Integer, default=0)
    advances: Mapped[int] = mapped_column(Integer, default=0)
    other_discount: Mapped[int] = mapped_column(Integer, default=0)
    ips_employee: Mapped[int] = mapped_column(Integer, default=0)
    gross: Mapped[int] = mapped_column(Integer, default=0)
    total_discounts: Mapped[int] = mapped_column(Integer, default=0)
    net: Mapped[int] = mapped_column(Integer, default=0)

    payroll: Mapped[Payroll] = relationship(back_populates="lines")
    employee: Mapped[Employee] = relationship(back_populates="payroll_lines")


class Vacation(Base):
    __tablename__ = "vacations"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    period_year: Mapped[int] = mapped_column(Integer)
    entitled_days: Mapped[int] = mapped_column(Integer, default=0)
    used_days: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Pendiente")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    employee: Mapped[Employee] = relationship()


class Aguinaldo(Base):
    __tablename__ = "aguinaldos"
    __table_args__ = (UniqueConstraint("employee_id", "year", name="uq_aguinaldo_employee_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    total_remunerations: Mapped[int] = mapped_column(Integer, default=0)
    calculated_amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="Borrador")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    employee: Mapped[Employee] = relationship()


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(100), default="General")
    title: Mapped[str] = mapped_column(String(200))
    stored_name: Mapped[str] = mapped_column(String(260))
    original_name: Mapped[str] = mapped_column(String(260))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    uploaded_by: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    company: Mapped[Company] = relationship(back_populates="documents")
    employee: Mapped[Optional[Employee]] = relationship()


class GeneratedCertificate(Base):
    __tablename__ = "generated_certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(120), default="Ciudad del Este")
    issue_date: Mapped[date] = mapped_column(Date, default=date.today)
    company_name_snapshot: Mapped[str] = mapped_column(String(220))
    employee_name_snapshot: Mapped[str] = mapped_column(String(220), default="")
    employee_document_snapshot: Mapped[str] = mapped_column(String(60), default="")
    position_snapshot: Mapped[str] = mapped_column(String(160), default="")
    admission_date_snapshot: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    salary_snapshot: Mapped[int] = mapped_column(Integer, default=0)
    observations: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="Borrador")
    created_by: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    company: Mapped[Company] = relationship(back_populates="generated_certificates")
    employee: Mapped[Optional[Employee]] = relationship(back_populates="generated_certificates")


class CompanyBranding(Base):
    __tablename__ = "company_branding"
    __table_args__ = (UniqueConstraint("company_id", name="uq_company_branding_company"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    logo_bytes: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    logo_content_type: Mapped[str] = mapped_column(String(80), default="")
    logo_filename: Mapped[str] = mapped_column(String(180), default="")
    primary_color: Mapped[str] = mapped_column(String(20), default="#173B86")
    secondary_color: Mapped[str] = mapped_column(String(20), default="#0B1F48")
    document_footer: Mapped[str] = mapped_column(String(240), default="Generado por Digit Laboral")
    signature_name: Mapped[str] = mapped_column(String(180), default="")
    signature_title: Mapped[str] = mapped_column(String(140), default="Representante legal")
    document_prefix: Mapped[str] = mapped_column(String(30), default="DL")
    show_ruc: Mapped[bool] = mapped_column(Boolean, default=True)
    show_contact: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    company: Mapped[Company] = relationship(back_populates="branding")


class CalculationRecord(Base):
    __tablename__ = "calculation_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    calculation_type: Mapped[str] = mapped_column(String(60), index=True)
    reference_period: Mapped[str] = mapped_column(String(20), default="")
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="Borrador")
    source: Mapped[str] = mapped_column(String(60), default="Calculadora")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    company: Mapped[Company] = relationship(back_populates="calculations")
    employee: Mapped[Optional[Employee]] = relationship(back_populates="calculations")


class AIInteraction(Base):
    __tablename__ = "ai_interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    studio_id: Mapped[Optional[int]] = mapped_column(ForeignKey("studios.id"), nullable=True, index=True)
    company_id: Mapped[Optional[int]] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(80), index=True)
    user_instruction: Mapped[str] = mapped_column(Text, default="")
    context_summary: Mapped[str] = mapped_column(Text, default="")
    response_text: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(60), default="Reglas internas")
    model_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="Completado")
    created_by: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    studio: Mapped[Optional[Studio]] = relationship(back_populates="ai_interactions")
    company: Mapped[Optional[Company]] = relationship(back_populates="ai_interactions")
    employee: Mapped[Optional[Employee]] = relationship(back_populates="ai_interactions")


class LaborArticle(Base):
    __tablename__ = "labor_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    law_number: Mapped[str] = mapped_column(String(40), default="Ley N.º 213/93")
    article_number: Mapped[str] = mapped_column(String(20), index=True)
    heading: Mapped[str] = mapped_column(String(220), default="")
    category: Mapped[str] = mapped_column(String(120), index=True)
    body: Mapped[str] = mapped_column(Text)
    content_status: Mapped[str] = mapped_column(String(60), default="Texto de referencia")
    amendment_note: Mapped[str] = mapped_column(String(240), default="")
    source_name: Mapped[str] = mapped_column(String(120), default="BACN")
    source_url: Mapped[str] = mapped_column(String(500))
    reviewed_at: Mapped[date] = mapped_column(Date, default=date.today)


class LaborParameter(Base):
    __tablename__ = "labor_parameters"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(180))
    value: Mapped[Decimal] = mapped_column(Numeric(16, 4))
    unit: Mapped[str] = mapped_column(String(40), default="Gs.")
    effective_from: Mapped[date] = mapped_column(Date)
    source_name: Mapped[str] = mapped_column(String(120), default="MTESS")
    source_url: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    studio_id: Mapped[Optional[int]] = mapped_column(ForeignKey("studios.id"), nullable=True, index=True)
    user_email: Mapped[str] = mapped_column(String(180))
    action: Mapped[str] = mapped_column(String(120))
    entity: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class EmployeeEvent(Base):
    __tablename__ = "employee_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True, default="General")
    title: Mapped[str] = mapped_column(String(180))
    detail: Mapped[str] = mapped_column(Text, default="")
    effective_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    employee: Mapped[Employee] = relationship()


class SalaryHistory(Base):
    __tablename__ = "salary_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    previous_salary: Mapped[int] = mapped_column(Integer, default=0)
    new_salary: Mapped[int] = mapped_column(Integer, default=0)
    effective_from: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    reason: Mapped[str] = mapped_column(String(240), default="Actualización salarial")
    created_by: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    employee: Mapped[Employee] = relationship()


class LaborDeadline(Base):
    __tablename__ = "labor_deadlines"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    deadline_type: Mapped[str] = mapped_column(String(80), default="General", index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    priority: Mapped[str] = mapped_column(String(30), default="Normal")
    status: Mapped[str] = mapped_column(String(30), default="Pendiente", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    company: Mapped[Company] = relationship()
    employee: Mapped[Optional[Employee]] = relationship()


class RequestWorkflow(Base):
    __tablename__ = "request_workflows"
    __table_args__ = (UniqueConstraint("request_id", name="uq_request_workflow_request"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("company_requests.id"), index=True)
    assigned_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    request: Mapped[CompanyRequest] = relationship()
    assigned_user: Mapped[Optional[User]] = relationship()


class RequestComment(Base):
    __tablename__ = "request_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("company_requests.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    author_name: Mapped[str] = mapped_column(String(180), default="")
    visibility: Mapped[str] = mapped_column(String(30), default="Empresa")
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    request: Mapped[CompanyRequest] = relationship()
    user: Mapped[Optional[User]] = relationship()


class RequestAttachment(Base):
    __tablename__ = "request_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("company_requests.id"), index=True)
    stored_name: Mapped[str] = mapped_column(String(260))
    original_name: Mapped[str] = mapped_column(String(260))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    uploaded_by: Mapped[str] = mapped_column(String(180), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    request: Mapped[CompanyRequest] = relationship()


class UserSecurity(Base):
    __tablename__ = "user_security"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_security_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    totp_secret: Mapped[str] = mapped_column(String(120), default="")
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    user: Mapped[User] = relationship()


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    requested_ip: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    user: Mapped[User] = relationship()


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    studio_id: Mapped[Optional[int]] = mapped_column(ForeignKey("studios.id"), nullable=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(180), default="", index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    ip_address: Mapped[str] = mapped_column(String(80), default="", index=True)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), index=True)

    user: Mapped[Optional[User]] = relationship()


class StudioPayment(Base):
    __tablename__ = "studio_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    studio_id: Mapped[int] = mapped_column(ForeignKey("studios.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    period: Mapped[str] = mapped_column(String(20), default="")
    payment_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    method: Mapped[str] = mapped_column(String(60), default="Transferencia")
    reference: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(30), default="Confirmado")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    studio: Mapped[Studio] = relationship()


class CompanyComplianceProfile(Base):
    __tablename__ = "company_compliance_profiles"
    __table_args__ = (UniqueConstraint("company_id", name="uq_company_compliance_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    department: Mapped[str] = mapped_column(String(100), default="")
    district: Mapped[str] = mapped_column(String(100), default="")
    locality: Mapped[str] = mapped_column(String(120), default="")
    economic_activity: Mapped[str] = mapped_column(String(220), default="")
    activity_code: Mapped[str] = mapped_column(String(60), default="")
    establishment_type: Mapped[str] = mapped_column(String(40), default="Matriz")
    legal_representative_document: Mapped[str] = mapped_column(String(40), default="")
    rei_status: Mapped[str] = mapped_column(String(30), default="Pendiente")
    reop_status: Mapped[str] = mapped_column(String(30), default="Pendiente")
    rei_last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reop_last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    company: Mapped[Company] = relationship()


class BranchComplianceProfile(Base):
    __tablename__ = "branch_compliance_profiles"
    __table_args__ = (UniqueConstraint("branch_id", name="uq_branch_compliance_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    ips_employer_number: Mapped[str] = mapped_column(String(80), default="")
    mtess_employer_number: Mapped[str] = mapped_column(String(80), default="")
    department: Mapped[str] = mapped_column(String(100), default="")
    district: Mapped[str] = mapped_column(String(100), default="")
    locality: Mapped[str] = mapped_column(String(120), default="")
    economic_activity: Mapped[str] = mapped_column(String(220), default="")
    activity_code: Mapped[str] = mapped_column(String(60), default="")
    establishment_type: Mapped[str] = mapped_column(String(40), default="Sucursal")
    rei_status: Mapped[str] = mapped_column(String(30), default="Pendiente")
    reop_status: Mapped[str] = mapped_column(String(30), default="Pendiente")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    branch: Mapped[Branch] = relationship()


class EmployeeComplianceProfile(Base):
    __tablename__ = "employee_compliance_profiles"
    __table_args__ = (UniqueConstraint("employee_id", name="uq_employee_compliance_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(30), default="CI")
    sex: Mapped[str] = mapped_column(String(30), default="")
    nationality: Mapped[str] = mapped_column(String(80), default="Paraguaya")
    marital_status: Mapped[str] = mapped_column(String(40), default="")
    birth_place: Mapped[str] = mapped_column(String(120), default="")
    department: Mapped[str] = mapped_column(String(100), default="")
    district: Mapped[str] = mapped_column(String(100), default="")
    profession: Mapped[str] = mapped_column(String(160), default="")
    occupation_code: Mapped[str] = mapped_column(String(60), default="")
    position_category: Mapped[str] = mapped_column(String(100), default="")
    work_schedule: Mapped[str] = mapped_column(String(120), default="")
    shift: Mapped[str] = mapped_column(String(60), default="Diurno")
    weekly_hours: Mapped[int] = mapped_column(Integer, default=48)
    salary_type: Mapped[str] = mapped_column(String(40), default="Mensual")
    dependent_children: Mapped[int] = mapped_column(Integer, default=0)
    indigenous: Mapped[bool] = mapped_column(Boolean, default=False)
    disability: Mapped[bool] = mapped_column(Boolean, default=False)
    rei_status: Mapped[str] = mapped_column(String(30), default="Pendiente")
    reop_status: Mapped[str] = mapped_column(String(30), default="Pendiente")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    employee: Mapped[Employee] = relationship()


class PayrollComplianceDetail(Base):
    __tablename__ = "payroll_compliance_details"
    __table_args__ = (UniqueConstraint("payroll_line_id", name="uq_payroll_compliance_detail"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    payroll_line_id: Mapped[int] = mapped_column(ForeignKey("payroll_lines.id"), index=True)
    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    payment_method: Mapped[str] = mapped_column(String(60), default="Transferencia")
    days_worked: Mapped[int] = mapped_column(Integer, default=30)
    hours_worked: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    night_surcharge: Mapped[int] = mapped_column(Integer, default=0)
    overtime_day: Mapped[int] = mapped_column(Integer, default=0)
    overtime_night: Mapped[int] = mapped_column(Integer, default=0)
    holidays: Mapped[int] = mapped_column(Integer, default=0)
    vacation_pay: Mapped[int] = mapped_column(Integer, default=0)
    family_allowance: Mapped[int] = mapped_column(Integer, default=0)
    other_income_detail: Mapped[int] = mapped_column(Integer, default=0)
    employer_ips: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    payroll_line: Mapped[PayrollLine] = relationship()


class ComplianceEvent(Base):
    __tablename__ = "compliance_events"
    __table_args__ = (UniqueConstraint("company_id", "authority", "source_key", name="uq_compliance_event_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    employee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("integration_batches.id"), nullable=True, index=True)
    authority: Mapped[str] = mapped_column(String(20), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="Borrador", index=True)
    source_key: Mapped[Optional[str]] = mapped_column(String(180), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    external_reference: Mapped[str] = mapped_column(String(160), default="")
    receipt_storage_key: Mapped[str] = mapped_column(String(260), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(180), default="")
    approved_by: Mapped[str] = mapped_column(String(180), default="")
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), index=True)

    company: Mapped[Company] = relationship()
    employee: Mapped[Optional[Employee]] = relationship()
    branch: Mapped[Optional[Branch]] = relationship()


class IntegrationBatch(Base):
    __tablename__ = "integration_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    studio_id: Mapped[int] = mapped_column(ForeignKey("studios.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    authority: Mapped[str] = mapped_column(String(20), index=True)
    batch_type: Mapped[str] = mapped_column(String(80), index=True)
    period: Mapped[str] = mapped_column(String(20), default="", index=True)
    status: Mapped[str] = mapped_column(String(30), default="Generado", index=True)
    file_name: Mapped[str] = mapped_column(String(260), default="")
    storage_key: Mapped[str] = mapped_column(String(300), default="")
    file_sha256: Mapped[str] = mapped_column(String(64), default="")
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    external_reference: Mapped[str] = mapped_column(String(160), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(180), default="")
    approved_by: Mapped[str] = mapped_column(String(180), default="")
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC), index=True)

    company: Mapped[Company] = relationship()


class IntegrationBatchItem(Base):
    __tablename__ = "integration_batch_items"
    __table_args__ = (UniqueConstraint("batch_id", "compliance_event_id", name="uq_batch_event"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("integration_batches.id"), index=True)
    compliance_event_id: Mapped[int] = mapped_column(ForeignKey("compliance_events.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="Incluido")
    response_message: Mapped[str] = mapped_column(Text, default="")

    batch: Mapped[IntegrationBatch] = relationship()
    compliance_event: Mapped[ComplianceEvent] = relationship(foreign_keys=[compliance_event_id])
