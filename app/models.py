from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="studio")
    companies: Mapped[list["Company"]] = relationship(back_populates="studio", cascade="all, delete-orphan")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    studio: Mapped[Studio] = relationship(back_populates="companies")
    branches: Mapped[list["Branch"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    employees: Mapped[list["Employee"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    requests: Mapped[list["CompanyRequest"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    users: Mapped[list[User]] = relationship(back_populates="company")
    payrolls: Mapped[list["Payroll"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="company", cascade="all, delete-orphan")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company: Mapped[Company] = relationship(back_populates="employees")
    branch: Mapped[Optional[Branch]] = relationship()
    payroll_lines: Mapped[list["PayrollLine"]] = relationship(back_populates="employee")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    company: Mapped[Company] = relationship(back_populates="documents")
    employee: Mapped[Optional[Employee]] = relationship()


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
