"""M2 review workflows.

Revision ID: a31c4ef902d2
Revises: 6e9f3b21a901
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a31c4ef902d2"
down_revision: Union[str, None] = "6e9f3b21a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("review_actions") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))
        batch_op.create_unique_constraint("uq_review_actions_idempotency_key", ["idempotency_key"])
    with op.batch_alter_table("po_amendments") as batch_op:
        batch_op.add_column(sa.Column("invoice_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_po_amendments_invoice_id_invoices", "invoices", ["invoice_id"], ["id"])
    op.create_table(
        "review_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("validation_result_id", sa.Integer(), sa.ForeignKey("validation_results.id"), nullable=True),
        sa.Column("exception_code", sa.String(64), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("OPEN", "RESOLVED", "CANCELLED", "SUPERSEDED", name="reviewcasestatus"), nullable=False),
        sa.Column("assigned_actor", sa.String(128), nullable=True),
        sa.Column("resolution_type", sa.String(64), nullable=True),
        sa.Column("resolution_details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_review_cases_invoice_id", "review_cases", ["invoice_id"])
    op.create_index("ix_review_cases_exception_code", "review_cases", ["exception_code"])
    op.create_index("ix_review_cases_category", "review_cases", ["category"])
    op.create_index("ix_review_cases_invoice_status", "review_cases", ["invoice_id", "status"])
    op.create_table(
        "field_corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("review_action_id", sa.Integer(), sa.ForeignKey("review_actions.id"), nullable=False, unique=True),
        sa.Column("field_path", sa.String(128), nullable=False),
        sa.Column("original_value_json", sa.JSON(), nullable=True),
        sa.Column("corrected_value_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_field_corrections_invoice_id", "field_corrections", ["invoice_id"])
    op.create_table(
        "po_confirmations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("po_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("review_action_id", sa.Integer(), sa.ForeignKey("review_actions.id"), nullable=False, unique=True),
        sa.Column("actor_name", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_po_confirmations_invoice_id", "po_confirmations", ["invoice_id"])


def downgrade() -> None:
    op.drop_table("po_confirmations")
    op.drop_table("field_corrections")
    op.drop_table("review_cases")
    with op.batch_alter_table("po_amendments") as batch_op:
        batch_op.drop_constraint("fk_po_amendments_invoice_id_invoices", type_="foreignkey")
        batch_op.drop_column("invoice_id")
    with op.batch_alter_table("review_actions") as batch_op:
        batch_op.drop_constraint("uq_review_actions_idempotency_key", type_="unique")
        batch_op.drop_column("idempotency_key")
