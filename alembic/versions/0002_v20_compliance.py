"""Add production compliance and REI/REOP interoperability tables.

Revision ID: 0002_v20_compliance
Revises: 0001_v19_baseline
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_v20_compliance"
down_revision = "0001_v19_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_compliance_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("department", sa.String(100), nullable=False, server_default=""),
        sa.Column("district", sa.String(100), nullable=False, server_default=""),
        sa.Column("locality", sa.String(120), nullable=False, server_default=""),
        sa.Column("economic_activity", sa.String(220), nullable=False, server_default=""),
        sa.Column("activity_code", sa.String(60), nullable=False, server_default=""),
        sa.Column("establishment_type", sa.String(40), nullable=False, server_default="Matriz"),
        sa.Column("legal_representative_document", sa.String(40), nullable=False, server_default=""),
        sa.Column("rei_status", sa.String(30), nullable=False, server_default="Pendiente"),
        sa.Column("reop_status", sa.String(30), nullable=False, server_default="Pendiente"),
        sa.Column("rei_last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("reop_last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", name="uq_company_compliance_profile"),
    )
    op.create_index("ix_company_compliance_profiles_company_id", "company_compliance_profiles", ["company_id"])

    op.create_table(
        "employee_compliance_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("document_type", sa.String(30), nullable=False, server_default="CI"),
        sa.Column("sex", sa.String(30), nullable=False, server_default=""),
        sa.Column("nationality", sa.String(80), nullable=False, server_default="Paraguaya"),
        sa.Column("marital_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("birth_place", sa.String(120), nullable=False, server_default=""),
        sa.Column("department", sa.String(100), nullable=False, server_default=""),
        sa.Column("district", sa.String(100), nullable=False, server_default=""),
        sa.Column("profession", sa.String(160), nullable=False, server_default=""),
        sa.Column("occupation_code", sa.String(60), nullable=False, server_default=""),
        sa.Column("position_category", sa.String(100), nullable=False, server_default=""),
        sa.Column("work_schedule", sa.String(120), nullable=False, server_default=""),
        sa.Column("shift", sa.String(60), nullable=False, server_default="Diurno"),
        sa.Column("weekly_hours", sa.Integer(), nullable=False, server_default="48"),
        sa.Column("salary_type", sa.String(40), nullable=False, server_default="Mensual"),
        sa.Column("dependent_children", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indigenous", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("disability", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rei_status", sa.String(30), nullable=False, server_default="Pendiente"),
        sa.Column("reop_status", sa.String(30), nullable=False, server_default="Pendiente"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("employee_id", name="uq_employee_compliance_profile"),
    )
    op.create_index("ix_employee_compliance_profiles_employee_id", "employee_compliance_profiles", ["employee_id"])

    op.create_table(
        "payroll_compliance_details",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payroll_line_id", sa.Integer(), sa.ForeignKey("payroll_lines.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("payment_method", sa.String(60), nullable=False, server_default="Transferencia"),
        sa.Column("days_worked", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("hours_worked", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("night_surcharge", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overtime_day", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overtime_night", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("holidays", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vacation_pay", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("family_allowance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("other_income_detail", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("employer_ips", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("payroll_line_id", name="uq_payroll_compliance_detail"),
    )
    op.create_index("ix_payroll_compliance_details_payroll_line_id", "payroll_compliance_details", ["payroll_line_id"])

    op.create_table(
        "integration_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("studio_id", sa.Integer(), sa.ForeignKey("studios.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("authority", sa.String(20), nullable=False),
        sa.Column("batch_type", sa.String(80), nullable=False),
        sa.Column("period", sa.String(20), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False, server_default="Generado"),
        sa.Column("file_name", sa.String(260), nullable=False, server_default=""),
        sa.Column("storage_key", sa.String(300), nullable=False, server_default=""),
        sa.Column("file_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("external_reference", sa.String(160), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(180), nullable=False, server_default=""),
        sa.Column("approved_by", sa.String(180), nullable=False, server_default=""),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("studio_id", "company_id", "authority", "batch_type", "period", "status", "created_at"):
        op.create_index(f"ix_integration_batches_{column}", "integration_batches", [column])

    op.create_table(
        "compliance_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("integration_batches.id"), nullable=True),
        sa.Column("authority", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="Borrador"),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("external_reference", sa.String(160), nullable=False, server_default=""),
        sa.Column("receipt_storage_key", sa.String(260), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(180), nullable=False, server_default=""),
        sa.Column("approved_by", sa.String(180), nullable=False, server_default=""),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("company_id", "employee_id", "batch_id", "authority", "event_type", "event_date", "due_date", "status", "created_at"):
        op.create_index(f"ix_compliance_events_{column}", "compliance_events", [column])

    op.create_table(
        "integration_batch_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("integration_batches.id"), nullable=False),
        sa.Column("compliance_event_id", sa.Integer(), sa.ForeignKey("compliance_events.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="Incluido"),
        sa.Column("response_message", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("batch_id", "compliance_event_id", name="uq_batch_event"),
    )
    op.create_index("ix_integration_batch_items_batch_id", "integration_batch_items", ["batch_id"])
    op.create_index("ix_integration_batch_items_compliance_event_id", "integration_batch_items", ["compliance_event_id"])


def downgrade() -> None:
    op.drop_table("integration_batch_items")
    op.drop_table("compliance_events")
    op.drop_table("integration_batches")
    op.drop_table("payroll_compliance_details")
    op.drop_table("employee_compliance_profiles")
    op.drop_table("company_compliance_profiles")
