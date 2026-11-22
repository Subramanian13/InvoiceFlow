"""M1B validation evidence and allocation idempotency.

Revision ID: 6e9f3b21a901
Revises: bcf5a294c034
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "6e9f3b21a901"
down_revision: Union[str, None] = "bcf5a294c034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("validation_results") as batch_op:
        batch_op.add_column(sa.Column("rule_name", sa.String(length=160), nullable=False, server_default="Validation rule"))
        batch_op.add_column(sa.Column("difference_json", sa.JSON(), nullable=True))
    with op.batch_alter_table("invoice_po_allocations") as batch_op:
        batch_op.create_unique_constraint("uq_invoice_po_allocations_invoice_id", ["invoice_id"])


def downgrade() -> None:
    with op.batch_alter_table("invoice_po_allocations") as batch_op:
        batch_op.drop_constraint("uq_invoice_po_allocations_invoice_id", type_="unique")
    with op.batch_alter_table("validation_results") as batch_op:
        batch_op.drop_column("difference_json")
        batch_op.drop_column("rule_name")
