"""Create independent employee exit and final-settlement workflows.

Revision ID: 0019_employee_exit_settlement
Revises: 0018_legacy_company_import
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_employee_exit_settlement"
down_revision = "0018_legacy_company_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_exits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("initiated_by", sa.String(30), nullable=False),
        sa.Column("include_exit_cause", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pre_notice_notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notice_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="Programado"),
        sa.Column("source", sa.String(40), nullable=False, server_default="Manual"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("constancia_certificate_id", sa.Integer(), sa.ForeignKey("generated_certificates.id"), nullable=True),
        sa.Column("created_by", sa.String(180), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('Programado', 'Efectivo', 'Cancelado')",
            name="ck_employee_exit_status",
        ),
    )
    op.create_index("ix_employee_exits_company_id", "employee_exits", ["company_id"])
    op.create_index("ix_employee_exits_employee_id", "employee_exits", ["employee_id"])
    op.create_index("ix_employee_exits_effective_date", "employee_exits", ["effective_date"])
    op.create_index("ix_employee_exits_status", "employee_exits", ["status"])
    op.create_index("ix_employee_exits_constancia_certificate_id", "employee_exits", ["constancia_certificate_id"])

    op.create_table(
        "final_settlements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("employee_exit_id", sa.Integer(), sa.ForeignKey("employee_exits.id"), nullable=False),
        sa.Column("calculation_record_id", sa.Integer(), sa.ForeignKey("calculation_records.id"), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="Pendiente de Cálculo"),
        sa.Column("calculated_amount", sa.Integer(), nullable=True),
        sa.Column("approved_amount", sa.Integer(), nullable=True),
        sa.Column("approved_by", sa.String(180), nullable=False, server_default=""),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("payment_amount", sa.Integer(), nullable=True),
        sa.Column("payment_method", sa.String(80), nullable=False, server_default=""),
        sa.Column("payment_reference", sa.String(180), nullable=False, server_default=""),
        sa.Column("receipt_document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("paid_by", sa.String(180), nullable=False, server_default=""),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(180), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("employee_exit_id", name="uq_final_settlement_employee_exit"),
        sa.UniqueConstraint("calculation_record_id", name="uq_final_settlement_calculation"),
        sa.CheckConstraint(
            "status IN ('Pendiente de Cálculo', 'En Revisión', 'Aprobada', 'Pagada')",
            name="ck_final_settlement_status",
        ),
        sa.CheckConstraint("calculated_amount IS NULL OR calculated_amount >= 0", name="ck_final_settlement_calculated_amount"),
        sa.CheckConstraint("approved_amount IS NULL OR approved_amount >= 0", name="ck_final_settlement_approved_amount"),
        sa.CheckConstraint("payment_amount IS NULL OR payment_amount >= 0", name="ck_final_settlement_payment_amount"),
    )
    op.create_index("ix_final_settlements_company_id", "final_settlements", ["company_id"])
    op.create_index("ix_final_settlements_employee_id", "final_settlements", ["employee_id"])
    op.create_index("ix_final_settlements_employee_exit_id", "final_settlements", ["employee_exit_id"])
    op.create_index("ix_final_settlements_calculation_record_id", "final_settlements", ["calculation_record_id"])
    op.create_index("ix_final_settlements_status", "final_settlements", ["status"])
    op.create_index("ix_final_settlements_receipt_document_id", "final_settlements", ["receipt_document_id"])


def downgrade() -> None:
    raise RuntimeError(
        "No se permite revertir automáticamente los procedimientos de egreso ni sus pagos: "
        "son registros laborales y contables auditables."
    )
