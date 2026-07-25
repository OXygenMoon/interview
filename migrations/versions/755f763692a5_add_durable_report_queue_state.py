"""add durable report queue state

Revision ID: 755f763692a5
Revises: fe4dca63a7ad
Create Date: 2026-07-25 19:58:20.755752

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '755f763692a5'
down_revision = 'fe4dca63a7ad'
branch_labels = None
depends_on = None


def upgrade():
    existing = {
        column['name']
        for column in sa.inspect(op.get_bind()).get_columns(
            'interview_sessions'
        )
    }
    columns = [
        sa.Column('report_job_id', sa.String(length=100), nullable=True),
        sa.Column(
            'report_queue_backend',
            sa.String(length=20),
            nullable=True,
        ),
        sa.Column(
            'report_queue_status',
            sa.String(length=30),
            nullable=True,
        ),
        sa.Column(
            'report_submission_count',
            sa.Integer(),
            server_default='0',
            nullable=False,
        ),
        sa.Column(
            'report_attempt_count',
            sa.Integer(),
            server_default='0',
            nullable=False,
        ),
        sa.Column('report_enqueued_at', sa.DateTime(), nullable=True),
        sa.Column('report_started_at', sa.DateTime(), nullable=True),
        sa.Column('report_finished_at', sa.DateTime(), nullable=True),
    ]
    missing = [column for column in columns if column.name not in existing]
    if missing:
        with op.batch_alter_table(
            'interview_sessions',
            schema=None,
        ) as batch_op:
            for column in missing:
                batch_op.add_column(column)


def downgrade():
    existing = {
        column['name']
        for column in sa.inspect(op.get_bind()).get_columns(
            'interview_sessions'
        )
    }
    names = [
        'report_finished_at',
        'report_started_at',
        'report_enqueued_at',
        'report_attempt_count',
        'report_submission_count',
        'report_queue_status',
        'report_queue_backend',
        'report_job_id',
    ]
    present = [name for name in names if name in existing]
    if present:
        with op.batch_alter_table(
            'interview_sessions',
            schema=None,
        ) as batch_op:
            for name in present:
                batch_op.drop_column(name)
