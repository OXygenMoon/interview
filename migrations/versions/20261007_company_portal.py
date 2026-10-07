"""Associate administrator-managed company accounts with their company."""
from alembic import op
import sqlalchemy as sa

revision = '20261007_company_portal'
down_revision = '20261007_test_accounts'
branch_labels = None
depends_on = None


def upgrade():
    if 'company_accounts' not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            'company_accounts',
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
            sa.Column('company_id', sa.Integer(), sa.ForeignKey('companies.id'), nullable=False),
            sa.Column('created_at', sa.DateTime()),
        )


def downgrade():
    op.drop_table('company_accounts')
