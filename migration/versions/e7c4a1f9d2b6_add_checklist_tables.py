"""add checklist tables (open/close)

Revision ID: e7c4a1f9d2b6
Revises: c3a7f2e4b8d1
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7c4a1f9d2b6'
down_revision: Union[str, None] = 'c3a7f2e4b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        'checklist_item_templates',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('location', sa.String(length=32), nullable=False),
        sa.Column('shift_type', sa.String(length=10), nullable=False),
        sa.Column('step_key', sa.String(length=64), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('prompt_text', sa.Text(), nullable=True),
        sa.Column('item_type', sa.String(length=16), nullable=False),
        sa.Column('needs_reference', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('reference_file_id', sa.String(length=255), nullable=True),
    )
    op.create_index('ix_checklist_item_templates_location', 'checklist_item_templates', ['location'])

    op.create_table(
        'checklist_submissions',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('location', sa.String(length=32), nullable=False),
        sa.Column('shift_type', sa.String(length=10), nullable=False),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='in_progress'),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )

    op.create_table(
        'checklist_answers',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('submission_id', sa.Integer, sa.ForeignKey('checklist_submissions.id'), nullable=False),
        sa.Column('item_id', sa.Integer, sa.ForeignKey('checklist_item_templates.id'), nullable=False),
        sa.Column('text_value', sa.Text(), nullable=True),
        sa.Column('photo_file_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('checklist_answers')
    op.drop_table('checklist_submissions')
    op.drop_index('ix_checklist_item_templates_location', table_name='checklist_item_templates')
    op.drop_table('checklist_item_templates')
