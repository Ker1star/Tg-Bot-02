"""create shift tasks tables rely

Revision ID: a60d3da8ece4
Revises: 75eeef254014
Create Date: 2025-11-28 13:52:19.954354

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a60d3da8ece4'
down_revision: Union[str, None] = '75eeef254014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        'shift_task_templates',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('weekday', sa.Integer(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_table(
        'shift_task_instances',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('template_id', sa.Integer, sa.ForeignKey('shift_task_templates.id'), nullable=False,),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_by_user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=True,),
    )

def downgrade():
    op.drop_table('shift_task_instances')
    op.drop_table('shift_task_templates')