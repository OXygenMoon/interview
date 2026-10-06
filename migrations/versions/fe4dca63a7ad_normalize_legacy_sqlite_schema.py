"""normalize legacy sqlite schema

Revision ID: fe4dca63a7ad
Revises: ffcb8eb89bc8
Create Date: 2026-07-25 19:43:38.995117

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fe4dca63a7ad'
down_revision = 'ffcb8eb89bc8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    chat_columns = {
        column['name']: column
        for column in inspector.get_columns('chat_messages')
    }
    audio_type = chat_columns['audio_urls']['type']
    if not isinstance(audio_type, sa.JSON):
        with op.batch_alter_table('chat_messages') as batch_op:
            batch_op.alter_column(
                'audio_urls',
                existing_type=audio_type,
                type_=sa.JSON(none_as_null=True),
                existing_nullable=True,
            )

    # Re-inspect after the first SQLite batch rebuild.
    inspector = sa.inspect(bind)
    session_columns = {
        column['name']: column
        for column in inspector.get_columns('interview_sessions')
    }
    indexes = {
        index['name']: index
        for index in inspector.get_indexes('interview_sessions')
    }
    unique_constraints = inspector.get_unique_constraints(
        'interview_sessions'
    )
    foreign_keys = inspector.get_foreign_keys('interview_sessions')

    parent_unique = any(
        constraint.get('column_names') == ['parent_session_id']
        for constraint in unique_constraints
    )
    if not parent_unique:
        # Some pre-Alembic deployments allowed more than one next-round
        # session for the same parent. Preserve every session, retain the
        # earliest link, and detach later duplicate children before adding the
        # model's uniqueness constraint.
        bind.execute(sa.text(
            'UPDATE interview_sessions '
            'SET parent_session_id = NULL '
            'WHERE parent_session_id IS NOT NULL '
            'AND id NOT IN ('
            'SELECT MIN(id) FROM interview_sessions '
            'WHERE parent_session_id IS NOT NULL '
            'GROUP BY parent_session_id'
            ')'
        ))
    legacy_parent_index = indexes.get(
        'uq_interview_sessions_parent_session_id'
    )
    if legacy_parent_index and not parent_unique:
        op.drop_index(
            'uq_interview_sessions_parent_session_id',
            table_name='interview_sessions',
        )

    existing_foreign_keys = {
        (
            tuple(foreign_key.get('constrained_columns') or ()),
            foreign_key.get('referred_table'),
            tuple(foreign_key.get('referred_columns') or ()),
        )
        for foreign_key in foreign_keys
    }
    resume_fk = (('resume_id',), 'resumes', ('id',))
    deleted_by_fk = (('deleted_by_id',), 'users', ('id',))

    position_type = session_columns['position_snapshot']['type']
    summary_type = session_columns['prior_round_summary']['type']
    operations_needed = any((
        not isinstance(position_type, sa.JSON),
        not isinstance(summary_type, sa.JSON),
        not parent_unique,
        resume_fk not in existing_foreign_keys,
        deleted_by_fk not in existing_foreign_keys,
    ))
    if operations_needed:
        with op.batch_alter_table('interview_sessions') as batch_op:
            if not isinstance(position_type, sa.JSON):
                batch_op.alter_column(
                    'position_snapshot',
                    existing_type=position_type,
                    type_=sa.JSON(),
                    existing_nullable=True,
                )
            if not isinstance(summary_type, sa.JSON):
                batch_op.alter_column(
                    'prior_round_summary',
                    existing_type=summary_type,
                    type_=sa.JSON(),
                    existing_nullable=True,
                )
            if not parent_unique:
                batch_op.create_unique_constraint(
                    'uq_interview_sessions_parent_session_id',
                    ['parent_session_id'],
                )
            if resume_fk not in existing_foreign_keys:
                batch_op.create_foreign_key(
                    'fk_interview_sessions_resume_id_resumes',
                    'resumes',
                    ['resume_id'],
                    ['id'],
                )
            if deleted_by_fk not in existing_foreign_keys:
                batch_op.create_foreign_key(
                    'fk_interview_sessions_deleted_by_id_users',
                    'users',
                    ['deleted_by_id'],
                    ['id'],
                )


def downgrade():
    # This revision only normalizes pre-Alembic physical schema to match the
    # baseline; the baseline's logical schema is identical.
    pass
