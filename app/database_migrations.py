"""Versioned database migration status and one-time legacy adoption."""

from pathlib import Path

import click
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from flask import current_app
from flask_migrate import stamp, upgrade
from sqlalchemy import inspect

from . import db


LEGACY_BASELINE_REVISION = 'ffcb8eb89bc8'


def _migration_directory():
    return Path(current_app.root_path).parent / 'migrations'


def _script_directory():
    if not (_migration_directory() / 'env.py').is_file():
        return None
    config = AlembicConfig()
    config.set_main_option('script_location', str(_migration_directory()))
    return ScriptDirectory.from_config(config)


def get_migration_status():
    """Return current/head revisions without changing the database."""
    script = _script_directory()
    head_revisions = tuple(sorted(script.get_heads())) if script else ()
    with db.engine.connect() as connection:
        current_revisions = tuple(sorted(
            MigrationContext.configure(connection).get_current_heads()
        ))
    return {
        'current_revisions': current_revisions,
        'head_revisions': head_revisions,
        'current_revision': ','.join(current_revisions) or None,
        'head_revision': ','.join(head_revisions) or None,
        'is_current': bool(head_revisions) and current_revisions == head_revisions,
    }


def _application_tables():
    return set(db.metadata.tables)


def _validate_model_shape():
    """Verify every mapped table/column exists before stamping a legacy DB."""
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(_application_tables() - existing_tables)
    missing_columns = {}
    for table_name in sorted(_application_tables() & existing_tables):
        existing = {
            column['name']
            for column in inspector.get_columns(table_name)
        }
        expected = set(db.metadata.tables[table_name].columns.keys())
        missing = sorted(expected - existing)
        if missing:
            missing_columns[table_name] = missing
    if missing_tables or missing_columns:
        details = []
        if missing_tables:
            details.append(f"缺少表: {', '.join(missing_tables)}")
        if missing_columns:
            formatted = '; '.join(
                f"{table}: {', '.join(columns)}"
                for table, columns in missing_columns.items()
            )
            details.append(f'缺少列: {formatted}')
        raise click.ClickException('；'.join(details))


def _run_maintenance():
    from .services.question_bank import repair_question_bank
    from .services.storage_cleanup import cleanup_runtime_files

    repair_question_bank()
    return cleanup_runtime_files(current_app)


def bootstrap_database():
    """Upgrade a fresh/versioned DB or safely adopt a pre-Alembic SQLite DB."""
    status = get_migration_status()
    if status['is_current']:
        maintenance = _run_maintenance()
        current_app.extensions['database_migration_status'] = status
        return {
            'action': 'already-current',
            'revision': status['head_revision'],
            'maintenance': maintenance,
        }

    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names()) - {'alembic_version'}
    if status['current_revisions']:
        upgrade(directory=str(_migration_directory()))
        action = 'upgraded'
    elif not existing_tables:
        upgrade(directory=str(_migration_directory()))
        action = 'created'
    else:
        if db.engine.dialect.name != 'sqlite':
            raise click.ClickException(
                '检测到未版本化的非 SQLite 数据库；请先备份并人工制定基线迁移。'
            )

        # One-time bridge for deployments created by db.create_all(). This is
        # deliberately only reachable through the explicit bootstrap command.
        db.create_all()
        from .schema_migrations import ensure_schema_compatibility
        ensure_schema_compatibility()
        _validate_model_shape()
        stamp(
            directory=str(_migration_directory()),
            revision=LEGACY_BASELINE_REVISION,
        )
        upgrade(directory=str(_migration_directory()))
        action = 'adopted-legacy'

    final_status = get_migration_status()
    if not final_status['is_current']:
        raise click.ClickException('迁移完成后数据库版本仍未到达 head')
    current_app.extensions['database_migration_status'] = final_status
    maintenance = _run_maintenance()
    return {
        'action': action,
        'revision': final_status['head_revision'],
        'maintenance': maintenance,
    }


def register_database_commands(app):
    @app.cli.command('bootstrap-db')
    def bootstrap_db_command():
        """Create, upgrade, or safely adopt the configured database."""
        result = bootstrap_database()
        click.echo(
            f"database={result['action']} revision={result['revision']}"
        )

    @app.cli.command('migration-status')
    def migration_status_command():
        """Show current and expected migration revisions."""
        status = get_migration_status()
        click.echo(
            f"current={status['current_revision'] or '-'} "
            f"head={status['head_revision'] or '-'} "
            f"ready={'yes' if status['is_current'] else 'no'}"
        )
