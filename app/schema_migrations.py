"""Small, idempotent compatibility migrations for the existing SQLite deployment.

The project historically used ``db.create_all()`` without a migration history.
That creates fresh databases correctly but cannot add columns to an existing
database. Run these migrations immediately after ``create_all`` so both fresh
and upgraded installations have the schema expected by the ORM.
"""

from datetime import datetime

from sqlalchemy import inspect, text

from . import db


SQLITE_COLUMNS = {
    'interview_sessions': {
        'last_activity': 'DATETIME',
        'reviewed': 'BOOLEAN DEFAULT 0',
        'abandoned': 'BOOLEAN DEFAULT 0',
        'round': 'INTEGER DEFAULT 1',
        'parent_session_id': 'INTEGER',
    },
    'chat_messages': {
        'audio_urls': 'TEXT',
    },
}

DEFAULT_CONFIGS = {
    'session_ttl_minutes': ('10', 'ongoing 面试无活动多久后判为 expired（分钟）'),
    'cooldown_abandon_minutes': ('10', '中途放弃后再次开始面试的冷却罚时（分钟）'),
    'cooldown_complete_minutes': ('30', '完成一次面试后再次开始的冷却时长（分钟）'),
    'cooldown_requires_review': ('true', '完成后是否强制复盘上次报告才能开始下一次'),
    'report_timeout_minutes': ('15', '报告生成卡在 processing 多久后判为 failed（分钟）'),
}


def ensure_schema_compatibility():
    """Upgrade an existing SQLite database in place, without deleting data."""
    if db.engine.dialect.name != 'sqlite':
        raise RuntimeError(
            'Automatic compatibility migrations currently support SQLite only. '
            'Use a database migration tool before switching database engines.'
        )

    # Gunicorn workers may initialize concurrently. BEGIN IMMEDIATE serializes
    # the inspect-and-alter sequence so two processes cannot both add a column.
    with db.engine.connect() as conn:
        conn.exec_driver_sql('BEGIN IMMEDIATE')
        table_names = set(inspect(conn).get_table_names())

        for table_name, columns in SQLITE_COLUMNS.items():
            if table_name not in table_names:
                continue
            existing = {column['name'] for column in inspect(conn).get_columns(table_name)}
            for column_name, declaration in columns.items():
                if column_name not in existing:
                    conn.exec_driver_sql(
                        f'ALTER TABLE "{table_name}" '
                        f'ADD COLUMN "{column_name}" {declaration}'
                    )

        if 'interview_sessions' in table_names:
            conn.execute(text(
                'UPDATE interview_sessions '
                'SET last_activity = start_time '
                'WHERE last_activity IS NULL'
            ))

            duplicate_parent = conn.execute(text(
                'SELECT parent_session_id '
                'FROM interview_sessions '
                'WHERE parent_session_id IS NOT NULL '
                'GROUP BY parent_session_id HAVING COUNT(*) > 1 '
                'LIMIT 1'
            )).first()
            schema = inspect(conn)
            parent_is_unique = any(
                constraint.get('column_names') == ['parent_session_id']
                for constraint in schema.get_unique_constraints('interview_sessions')
            ) or any(
                index.get('unique')
                and index.get('column_names') == ['parent_session_id']
                for index in schema.get_indexes('interview_sessions')
            )
            if duplicate_parent is None and not parent_is_unique:
                conn.exec_driver_sql(
                    'CREATE UNIQUE INDEX IF NOT EXISTS '
                    'uq_interview_sessions_parent_session_id '
                    'ON interview_sessions(parent_session_id) '
                    'WHERE parent_session_id IS NOT NULL'
                )
            elif duplicate_parent is not None and not parent_is_unique:
                print(
                    '[schema] Duplicate parent_session_id values found; '
                    'skipping the unique index until they are reviewed.'
                )

        if 'system_configs' in table_names:
            for key, (value, description) in DEFAULT_CONFIGS.items():
                conn.execute(text(
                    'INSERT INTO system_configs '
                    '("key", value, description, updated_at) '
                    'SELECT :key, :value, :description, :updated_at '
                    'WHERE NOT EXISTS ('
                    'SELECT 1 FROM system_configs WHERE "key" = :key'
                    ')'
                ), {
                    'key': key,
                    'value': value,
                    'description': description,
                    'updated_at': datetime.now(),
                })

        conn.commit()
