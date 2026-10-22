"""Solicitudes estructuradas, aprobaciones y notificaciones."""
from alembic import op
import sqlalchemy as sa

revision = "0007_request_notifications"
down_revision = "0006_payroll_calculation_inputs"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    request_columns = _columns("company_requests")
    request_additions = [
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("period_year", sa.Integer(), nullable=True),
        sa.Column("requested_days", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("leave_type", sa.String(100), nullable=False, server_default=""),
        sa.Column("hours_requested", sa.Numeric(6, 2), nullable=True),
    ]
    for column in request_additions:
        if column.name not in request_columns:
            op.add_column("company_requests", column)
    request_indexes = _indexes("company_requests")
    if "ix_company_requests_requested_by_user_id" not in request_indexes:
        op.create_index("ix_company_requests_requested_by_user_id", "company_requests", ["requested_by_user_id"])
    if "ix_company_requests_employee_id" not in request_indexes:
        op.create_index("ix_company_requests_employee_id", "company_requests", ["employee_id"])

    workflow_columns = _columns("request_workflows")
    for column in [
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
    ]:
        if column.name not in workflow_columns:
            op.add_column("request_workflows", column)

    if not sa.inspect(op.get_bind()).has_table("notifications"):
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("studio_id", sa.Integer(), sa.ForeignKey("studios.id"), nullable=True),
            sa.Column("recipient_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("target_url", sa.String(500), nullable=False, server_default="/app/notifications"),
            sa.Column("related_request_id", sa.Integer(), sa.ForeignKey("company_requests.id"), nullable=True),
            sa.Column("dedupe_key", sa.String(300), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
        )
    notification_indexes = _indexes("notifications")
    for name, columns in [
        ("ix_notifications_studio_id", ["studio_id"]),
        ("ix_notifications_recipient_user_id", ["recipient_user_id"]),
        ("ix_notifications_event_type", ["event_type"]),
        ("ix_notifications_related_request_id", ["related_request_id"]),
        ("ix_notifications_created_at", ["created_at"]),
    ]:
        if name not in notification_indexes:
            op.create_index(name, "notifications", columns)

    if not sa.inspect(op.get_bind()).has_table("notification_deliveries"):
        op.create_table(
            "notification_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("notification_id", sa.Integer(), sa.ForeignKey("notifications.id"), nullable=False),
            sa.Column("channel", sa.String(20), nullable=False, server_default="email"),
            sa.Column("status", sa.String(30), nullable=False, server_default="Pendiente"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
        )
    delivery_indexes = _indexes("notification_deliveries")
    for name, columns in [
        ("ix_notification_deliveries_notification_id", ["notification_id"]),
        ("ix_notification_deliveries_status", ["status"]),
    ]:
        if name not in delivery_indexes:
            op.create_index(name, "notification_deliveries", columns)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("notification_deliveries"):
        op.drop_table("notification_deliveries")
    if sa.inspect(bind).has_table("notifications"):
        op.drop_table("notifications")
    workflow_columns = _columns("request_workflows")
    with op.batch_alter_table("request_workflows") as batch:
        for name in ("applied_at", "applied", "decision_notes", "approved_at", "approved_by_user_id"):
            if name in workflow_columns:
                batch.drop_column(name)
    request_columns = _columns("company_requests")
    request_indexes = _indexes("company_requests")
    for index in ("ix_company_requests_requested_by_user_id", "ix_company_requests_employee_id"):
        if index in request_indexes:
            op.drop_index(index, table_name="company_requests")
    with op.batch_alter_table("company_requests") as batch:
        for name in ("hours_requested", "leave_type", "amount", "requested_days", "period_year", "end_date", "start_date", "effective_date", "employee_id", "requested_by_user_id"):
            if name in request_columns:
                batch.drop_column(name)
