"""One-time compatibility bridge for databases created before Alembic.

Only ``flask --app run.py bootstrap-db`` calls this module when adopting an
existing unversioned SQLite database. New and already-versioned databases use
the migrations in ``migrations/`` exclusively.
"""

from datetime import datetime

from sqlalchemy import inspect, text

from . import db


SQLITE_COLUMNS = {
    'users': {
        'active': 'BOOLEAN NOT NULL DEFAULT 1',
        'must_change_password': 'BOOLEAN NOT NULL DEFAULT 0',
        'deactivated_at': 'DATETIME',
    },
    'interview_sessions': {
        'last_activity': 'DATETIME',
        'reviewed': 'BOOLEAN DEFAULT 0',
        'abandoned': 'BOOLEAN DEFAULT 0',
        'round': 'INTEGER DEFAULT 1',
        'parent_session_id': 'INTEGER',
        'deleted_at': 'DATETIME',
        'deleted_by_id': 'INTEGER',
        'deletion_reason': 'VARCHAR(255)',
        'status_before_delete': 'VARCHAR(20)',
        'evaluation_source': 'VARCHAR(30)',
        'report_model': 'VARCHAR(100)',
        'report_prompt_version': 'VARCHAR(50)',
        'report_error': 'TEXT',
        'report_job_id': 'VARCHAR(100)',
        'report_queue_backend': 'VARCHAR(20)',
        'report_queue_status': 'VARCHAR(30)',
        'report_submission_count': 'INTEGER NOT NULL DEFAULT 0',
        'report_attempt_count': 'INTEGER NOT NULL DEFAULT 0',
        'report_enqueued_at': 'DATETIME',
        'report_started_at': 'DATETIME',
        'report_finished_at': 'DATETIME',
        'resume_id': 'INTEGER',
        'resume_snapshot': 'TEXT',
        'resume_document_snapshot': 'JSON',
        'position_snapshot': 'TEXT',
        'prior_round_summary': 'TEXT',
        'llm_model': 'VARCHAR(100)',
        'prompt_version': 'VARCHAR(50)',
    },
    'chat_messages': {
        'visual_image': 'BLOB',
        'visual_captured_at': 'DATETIME',
        'audio_urls': 'TEXT',
        'generation_status': "VARCHAR(30) NOT NULL DEFAULT 'completed'",
        'model_name': 'VARCHAR(100)',
        'error_message': 'TEXT',
    },
}

DEFAULT_CONFIGS = {
    'session_ttl_minutes': ('10', 'ongoing 面试无活动多久后判为 expired（分钟）'),
    'cooldown_abandon_minutes': ('10', '中途放弃后再次开始面试的冷却罚时（分钟）'),
    'cooldown_complete_minutes': ('30', '完成一次面试后再次开始的冷却时长（分钟）'),
    'cooldown_requires_review': ('true', '完成后是否强制复盘上次报告才能开始下一次'),
    'report_timeout_minutes': ('15', '报告生成卡在 processing 多久后判为 failed（分钟）'),
    'audio_retention_days': ('30', 'TTS 音频保留天数，到期后清空数据库引用并删除文件'),
    'temp_retention_hours': ('24', '临时上传文件最大保留小时数'),
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
            if duplicate_parent is not None and not parent_is_unique:
                result = conn.execute(text(
                    'UPDATE interview_sessions '
                    'SET parent_session_id = NULL '
                    'WHERE parent_session_id IS NOT NULL '
                    'AND id NOT IN ('
                    'SELECT MIN(id) FROM interview_sessions '
                    'WHERE parent_session_id IS NOT NULL '
                    'GROUP BY parent_session_id'
                    ')'
                ))
                print(
                    '[schema] Normalized invalid interview round links: '
                    f'detached {result.rowcount} duplicate child session(s); '
                    'the earliest child for each parent was retained.'
                )

            if not parent_is_unique:
                conn.exec_driver_sql(
                    'CREATE UNIQUE INDEX IF NOT EXISTS '
                    'uq_interview_sessions_parent_session_id '
                    'ON interview_sessions(parent_session_id) '
                    'WHERE parent_session_id IS NOT NULL'
                )

        if 'chat_messages' in table_names:
            # SQLAlchemy's historical JSON default stored Python None as the
            # text literal "null". Normalize it to SQL NULL so retention
            # queries and database audits do not treat it as a live link.
            chat_columns = {
                column['name']
                for column in inspect(conn).get_columns('chat_messages')
            }
            if 'audio_urls' in chat_columns:
                conn.execute(text(
                    'UPDATE chat_messages SET audio_urls = NULL '
                    'WHERE lower(trim(audio_urls)) = \'null\''
                ))

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

        # Older form submissions incorrectly marked failed quizzes as completed.
        # Preserve those scores as attempts, then reopen the lesson for retry.
        if {'learning_attempts', 'user_learning_progress', 'learning_materials'} <= table_names:
            conn.execute(text(
                'INSERT INTO learning_attempts '
                '(user_id, material_id, score, passed, answers, attempted_at) '
                'SELECT p.user_id, p.material_id, p.score, 0, NULL, p.completed_at '
                'FROM user_learning_progress p '
                'JOIN learning_materials m ON m.id = p.material_id '
                'WHERE m.material_type = \'quiz\' AND p.score < 80'
            ))
            conn.execute(text(
                'DELETE FROM user_learning_progress '
                'WHERE id IN ('
                'SELECT p.id FROM user_learning_progress p '
                'JOIN learning_materials m ON m.id = p.material_id '
                'WHERE m.material_type = \'quiz\' AND p.score < 80'
                ')'
            ))

        conn.commit()
