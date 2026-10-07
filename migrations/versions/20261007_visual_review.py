"""Keep timestamped camera snapshots with interview answers.

Revision ID: 20261007_visual_review
Revises: 20261006_account_links
"""
from alembic import op
import sqlalchemy as sa

revision = '20261007_visual_review'
down_revision = '20261006_account_links'
branch_labels = None
depends_on = None


def upgrade():
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('chat_messages')}
    with op.batch_alter_table('chat_messages') as batch_op:
        for column in (
            sa.Column('visual_image', sa.LargeBinary(), nullable=True),
            sa.Column('visual_captured_at', sa.DateTime(), nullable=True),
        ):
            if column.name not in existing:
                batch_op.add_column(column)


def downgrade():
    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.drop_column('visual_captured_at')
        batch_op.drop_column('visual_image')
