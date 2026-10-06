"""Add account associations and single-use authorization tickets.

Revision ID: 20261006_account_links
Revises: 755f763692a5
"""
from alembic import op
import sqlalchemy as sa

revision = '20261006_account_links'
down_revision = '755f763692a5'
branch_labels = None
depends_on = None


def upgrade():
    # Legacy bootstrap creates new model tables before adopting the baseline.
    existing = sa.inspect(op.get_bind()).get_table_names()
    if 'account_links' not in existing:
        op.create_table('account_links',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('interview_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
            sa.Column('wikibook_user_id', sa.Integer(), nullable=False, unique=True),
            sa.Column('interview_username', sa.String(80), nullable=False),
            sa.Column('wikibook_username', sa.String(80), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
    if 'account_link_tickets' not in existing:
        op.create_table('account_link_tickets',
            sa.Column('digest', sa.String(64), primary_key=True),
            sa.Column('purpose', sa.String(10), nullable=False),
            sa.Column('source_site', sa.String(10), nullable=False),
            sa.Column('source_user_id', sa.Integer(), nullable=False),
            sa.Column('source_version', sa.String(64), nullable=False),
            sa.Column('source_username', sa.String(80), nullable=False),
            sa.Column('target_user_id', sa.Integer()),
            sa.Column('target_version', sa.String(64)),
            sa.Column('link_id', sa.String(36)),
            sa.Column('state_digest', sa.String(64)),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('consumed', sa.Boolean(), nullable=False),
        )
        op.create_index('ix_account_link_tickets_expires_at', 'account_link_tickets', ['expires_at'])


def downgrade():
    op.drop_table('account_link_tickets')
    op.drop_table('account_links')
