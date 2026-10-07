"""Add exclusive browser leases for the test account pool."""
from alembic import op
import sqlalchemy as sa

revision = '20261007_test_accounts'
down_revision = '20261007_visual_review'
branch_labels = None
depends_on = None


def upgrade():
    # Legacy bootstrap may already have created this mapped table.
    if 'test_accounts' not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            'test_accounts',
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
            sa.Column('lease_token', sa.String(64)),
            sa.Column('lease_expires_at', sa.DateTime()),
        )


def downgrade():
    op.drop_table('test_accounts')
