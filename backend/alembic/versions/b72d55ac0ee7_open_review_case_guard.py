"""Prevent duplicate open review cases.

Revision ID: b72d55ac0ee7
Revises: a31c4ef902d2
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b72d55ac0ee7"
down_revision: Union[str, None] = "a31c4ef902d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("uq_review_cases_open_issue", "review_cases", ["invoice_id", "exception_code"],
                    unique=True, sqlite_where=sa.text("status = 'OPEN'"), postgresql_where=sa.text("status = 'OPEN'"))


def downgrade() -> None:
    op.drop_index("uq_review_cases_open_issue", table_name="review_cases")
