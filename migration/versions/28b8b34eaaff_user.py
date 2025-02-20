"""User

Revision ID: 28b8b34eaaff
Revises: cf1bad6a3297
Create Date: 2025-02-19 19:58:54.217562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28b8b34eaaff'
down_revision: Union[str, None] = 'cf1bad6a3297'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
