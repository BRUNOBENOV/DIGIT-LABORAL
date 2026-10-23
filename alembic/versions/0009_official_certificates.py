"""Track official MTESS and IPS certificates without impersonating the issuer.

Revision ID: 0009_official_certificates
Revises: 0008_company_logo_presentation
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_official_certificates"
down_revision = "0008_company_logo_presentation"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    # The application's legacy-schema reconciliation calls metadata.create_all()
    # before Alembic upgrades. Existing tables are not altered by create_all(), so
    # add this optional BLOB column explicitly for durable official originals when
    # the installation uses local/ephemeral file storage.
    if "documents" in _tables() and "content_bytes" not in _columns("documents"):
        op.add_column("documents", sa.Column("content_bytes", sa.LargeBinary(), nullable=True))

    # Make this revision safe if create_all() has already created the tracker table.
    if "official_certificates" not in _tables():
        op.create_table(
            "official_certificates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=True),
            sa.Column("institution", sa.String(10), nullable=False),
            sa.Column("certificate_type", sa.String(80), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="Pendiente"),
            sa.Column("request_date", sa.Date(), nullable=False),
            sa.Column("issue_date", sa.Date(), nullable=True),
            sa.Column("expiry_date", sa.Date(), nullable=True),
            sa.Column("official_number", sa.String(120), nullable=False, server_default=""),
            sa.Column("result_status", sa.String(30), nullable=False, server_default=""),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(180), nullable=False, server_default=""),
            sa.Column("updated_by", sa.String(180), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    expected_indexes = {
        "ix_official_certificates_company_id": ["company_id"],
        "ix_official_certificates_employee_id": ["employee_id"],
        "ix_official_certificates_institution": ["institution"],
        "ix_official_certificates_certificate_type": ["certificate_type"],
        "ix_official_certificates_status": ["status"],
        "ix_official_certificates_expiry_date": ["expiry_date"],
        "ix_official_certificates_document_id": ["document_id"],
    }
    indexes = _indexes("official_certificates")
    for name, columns in expected_indexes.items():
        if name not in indexes:
            op.create_index(name, "official_certificates", columns)


def downgrade() -> None:
    if "official_certificates" in _tables():
        op.drop_table("official_certificates")
    if "documents" in _tables() and "content_bytes" in _columns("documents"):
        op.drop_column("documents", "content_bytes")
