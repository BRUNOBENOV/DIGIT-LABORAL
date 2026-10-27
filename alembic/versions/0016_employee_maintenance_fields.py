"""Add employee legajo codes, company sections, and modification metadata.

Revision ID: 0016_employee_maintenance_fields
Revises: 0015_company_maintenance_fields
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0016_employee_maintenance_fields"
down_revision = "0015_company_maintenance_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "company_sections" not in tables:
        op.create_table(
            "company_sections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("section_code", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=140), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_by", sa.String(length=180), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint("company_id", "section_code", name="uq_company_section_code"),
            sa.UniqueConstraint("company_id", "name", name="uq_company_section_name"),
        )
        op.create_index("ix_company_sections_company_id", "company_sections", ["company_id"])
    else:
        existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("company_sections")}
        if "ix_company_sections_company_id" not in existing_indexes:
            op.create_index("ix_company_sections_company_id", "company_sections", ["company_id"])

    columns = {item["name"] for item in sa.inspect(bind).get_columns("employees")}
    additions = [
        ("employee_code", sa.Column("employee_code", sa.Integer(), nullable=True)),
        ("section_id", sa.Column("section_id", sa.Integer(), sa.ForeignKey("company_sections.id"), nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime(), nullable=True)),
        ("updated_by", sa.Column("updated_by", sa.String(length=180), nullable=False, server_default="")),
    ]
    for name, column in additions:
        if name not in columns:
            op.add_column("employees", column)

    rows = bind.execute(sa.text(
        "SELECT id, company_id, employee_code, created_at, updated_at "
        "FROM employees ORDER BY company_id, id"
    )).mappings().all()
    used: dict[int, set[int]] = {}
    next_code: dict[int, int] = {}
    for row in rows:
        company_id = int(row["company_id"])
        used.setdefault(company_id, set())
        if row["employee_code"] is not None:
            code = int(row["employee_code"])
            used[company_id].add(code)
            next_code[company_id] = max(next_code.get(company_id, 0), code)

    for row in rows:
        company_id = int(row["company_id"])
        if row["employee_code"] is None:
            code = next_code.get(company_id, 0) + 1
            while code in used[company_id]:
                code += 1
            bind.execute(
                sa.text("UPDATE employees SET employee_code = :code WHERE id = :employee_id"),
                {"code": code, "employee_id": row["id"]},
            )
            used[company_id].add(code)
            next_code[company_id] = code
        if row["updated_at"] is None:
            bind.execute(
                sa.text(
                    "UPDATE employees SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
                    "WHERE id = :employee_id"
                ),
                {"employee_id": row["id"]},
            )

    if "employee_compliance_profiles" in set(sa.inspect(bind).get_table_names()):
        profile_columns = {
            item["name"] for item in sa.inspect(bind).get_columns("employee_compliance_profiles")
        }
        if "daily_hours" not in profile_columns:
            op.add_column(
                "employee_compliance_profiles",
                sa.Column("daily_hours", sa.Integer(), nullable=False, server_default="8"),
            )
        if "ips_number" not in profile_columns:
            op.add_column(
                "employee_compliance_profiles",
                sa.Column("ips_number", sa.String(length=80), nullable=False, server_default=""),
            )

    inspector = sa.inspect(bind)
    employee_indexes = {item["name"] for item in inspector.get_indexes("employees")}
    employee_constraints = {item.get("name") for item in inspector.get_unique_constraints("employees")}
    if "ix_employees_employee_code" not in employee_indexes:
        op.create_index("ix_employees_employee_code", "employees", ["employee_code"])
    if "ix_employees_section_id" not in employee_indexes:
        op.create_index("ix_employees_section_id", "employees", ["section_id"])
    if "uq_employee_code_per_company" not in employee_indexes and "uq_employee_code_per_company" not in employee_constraints:
        op.create_index(
            "uq_employee_code_per_company",
            "employees",
            ["company_id", "employee_code"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("employees")}
    for name in ("uq_employee_code_per_company", "ix_employees_employee_code", "ix_employees_section_id"):
        if name in indexes:
            op.drop_index(name, table_name="employees")

    columns = {item["name"] for item in sa.inspect(bind).get_columns("employees")}
    for name in ("updated_by", "updated_at", "section_id", "employee_code"):
        if name in columns:
            op.drop_column("employees", name)

    if "employee_compliance_profiles" in sa.inspect(bind).get_table_names():
        profile_columns = {
            item["name"] for item in sa.inspect(bind).get_columns("employee_compliance_profiles")
        }
        for name in ("ips_number", "daily_hours"):
            if name in profile_columns:
                op.drop_column("employee_compliance_profiles", name)

    if "company_sections" in sa.inspect(bind).get_table_names():
        section_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("company_sections")}
        if "ix_company_sections_company_id" in section_indexes:
            op.drop_index("ix_company_sections_company_id", table_name="company_sections")
        op.drop_table("company_sections")
