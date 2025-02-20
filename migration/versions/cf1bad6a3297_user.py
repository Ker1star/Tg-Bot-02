"""User

Revision ID: cf1bad6a3297
Revises: 4e44f312ee21
Create Date: 2025-02-19 19:55:50.412473

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cf1bad6a3297'
down_revision: Union[str, None] = '4e44f312ee21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
