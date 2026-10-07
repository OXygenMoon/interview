"""Preserve the submitted resume layout and visible structured content."""
from alembic import op
import sqlalchemy as sa

revision = '20261008_resume_document'
down_revision = '20261007_company_portal'
branch_labels = None
depends_on = None


def upgrade():
    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('interview_sessions')}
    if 'resume_document_snapshot' not in columns:
        with op.batch_alter_table('interview_sessions') as batch:
            batch.add_column(sa.Column('resume_document_snapshot', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('interview_sessions') as batch:
        batch.drop_column('resume_document_snapshot')
