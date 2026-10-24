"""Add aggregated local recruitment and independent source sync state."""
from alembic import op
import sqlalchemy as sa

revision = '20261025_local_recruitment'
down_revision = '20261022_learning_video'
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'recruitment_jobs' not in tables:
        op.create_table('recruitment_jobs',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('source', sa.String(30), nullable=False),
            sa.Column('source_url', sa.String(1000), nullable=False),
            sa.Column('group_key', sa.String(64), nullable=False),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('company', sa.String(300), nullable=False),
            sa.Column('district', sa.String(30), nullable=False),
            sa.Column('address', sa.String(500), nullable=False),
            sa.Column('salary', sa.String(100), nullable=False),
            sa.Column('experience', sa.String(100), nullable=False),
            sa.Column('education', sa.String(100), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('published_at', sa.String(100), nullable=False),
            sa.Column('expires_at', sa.DateTime()),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('first_seen_at', sa.DateTime(), nullable=False),
            sa.Column('last_seen_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('source', 'source_url', name='uq_recruitment_source_url'))
        for column in ('group_key', 'district', 'last_seen_at'):
            op.create_index(f'ix_recruitment_jobs_{column}', 'recruitment_jobs', [column])
    if 'recruitment_syncs' not in tables:
        op.create_table('recruitment_syncs',
            sa.Column('source', sa.String(30), primary_key=True),
            sa.Column('status', sa.String(30), nullable=False),
            sa.Column('message', sa.String(500), nullable=False),
            sa.Column('started_at', sa.DateTime()),
            sa.Column('finished_at', sa.DateTime()),
            sa.Column('succeeded_at', sa.DateTime()),
            sa.Column('job_count', sa.Integer(), nullable=False),
            sa.Column('lease_token', sa.String(64)))



def downgrade():
    op.drop_table('recruitment_syncs')
    op.drop_table('recruitment_jobs')
