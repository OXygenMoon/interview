"""Add uploaded and Bilibili video lessons."""
from alembic import op
import sqlalchemy as sa

revision = '20261022_learning_video'
down_revision = '20261008_resume_document'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('learning_materials')}
    with op.batch_alter_table('learning_materials') as batch:
        if 'video_source' not in columns:
            batch.add_column(sa.Column('video_source', sa.String(20), nullable=True))
        if 'video_url' not in columns:
            batch.add_column(sa.Column('video_url', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('learning_materials') as batch:
        batch.drop_column('video_url')
        batch.drop_column('video_source')
