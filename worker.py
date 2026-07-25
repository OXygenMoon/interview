"""Dedicated RQ worker entrypoint for interview report generation."""

from dotenv import load_dotenv


load_dotenv()


def main():
    from app import create_app
    from app.database_migrations import get_migration_status
    from app.services.report_queue import run_worker

    app = create_app()
    with app.app_context():
        migration = get_migration_status()
        if not migration['is_current']:
            raise RuntimeError(
                '数据库迁移未完成，拒绝启动报告 Worker；'
                '请先运行 `flask --app run.py bootstrap-db`。'
            )
        run_worker()


if __name__ == '__main__':
    main()
