"""allow multiple field corrections per review action

Revision ID: c83f20d21d4a
Revises: b72d55ac0ee7
"""
from alembic import op
import sqlalchemy as sa

revision = "c83f20d21d4a"
down_revision = "b72d55ac0ee7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("field_corrections") as batch:
        batch.drop_constraint("uq_field_corrections_review_action_id", type_="unique")
        batch.create_index("ix_field_corrections_review_action_id", ["review_action_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("field_corrections") as batch:
        batch.drop_index("ix_field_corrections_review_action_id")
        batch.create_unique_constraint("uq_field_corrections_review_action_id", ["review_action_id"])
