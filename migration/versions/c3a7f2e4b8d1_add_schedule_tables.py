"""add schedule tables (weight, availability, assignments, replacements)

Revision ID: c3a7f2e4b8d1
Revises: a60d3da8ece4
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a7f2e4b8d1'
down_revision: Union[str, None] = 'a60d3da8ece4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column('users', sa.Column('exam_score', sa.Float(), nullable=False, server_default='0.15'))
    op.add_column('users', sa.Column('admin_score', sa.Float(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('hire_date', sa.Date(), nullable=True))

    op.create_table(
        'schedule_periods',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='collecting'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'availability_responses',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('period_id', sa.Integer, sa.ForeignKey('schedule_periods.id'), nullable=False),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'availability_constraints',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('response_id', sa.Integer, sa.ForeignKey('availability_responses.id'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('constraint_type', sa.String(length=20), nullable=False),
        sa.Column('time_value', sa.Time(), nullable=True),
    )

    op.create_table(
        'shift_assignments',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('period_id', sa.Integer, sa.ForeignKey('schedule_periods.id'), nullable=False),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='planned'),
        sa.Column('replaced_by_user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('is_flagged', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('flag_reason', sa.Text(), nullable=True),
    )

    op.create_table(
        'replacement_broadcast_messages',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('assignment_id', sa.Integer, sa.ForeignKey('shift_assignments.id'), nullable=False),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('message_id', sa.Integer(), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('replacement_broadcast_messages')
    op.drop_table('shift_assignments')
    op.drop_table('availability_constraints')
    op.drop_table('availability_responses')
    op.drop_table('schedule_periods')
    op.drop_column('users', 'hire_date')
    op.drop_column('users', 'admin_score')
    op.drop_column('users', 'exam_score')
