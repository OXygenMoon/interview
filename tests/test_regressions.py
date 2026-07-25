import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app import create_app, db
from app.config import Config
from app.models import ChatMessage, InterviewSession, User


def login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


class BusinessRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Config.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        cls.app = create_app()
        cls.app.config.update(TESTING=True)

    def setUp(self):
        with self.app.app_context():
            db.drop_all()
            db.create_all()

            self.student = User(
                username='student',
                role='student',
                class_name='软件一班',
            )
            self.teacher = User(
                username='teacher',
                role='teacher',
                class_name='软件一班',
            )
            self.student.set_password('test')
            self.teacher.set_password('test')
            db.session.add_all([self.student, self.teacher])
            db.session.commit()
            self.student_id = self.student.id
            self.teacher_id = self.teacher.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()

    def test_weak_questions_only_count_reviewed_user_answers(self):
        with self.app.app_context():
            finished = InterviewSession(
                user_id=self.student_id,
                status='completed',
                target_role='Python 工程师',
                total_score=80,
            )
            db.session.add(finished)
            db.session.commit()
            db.session.add_all([
                ChatMessage(
                    session_id=finished.id,
                    sender='ai',
                    content='请介绍一次你解决线上故障的经历。',
                ),
                ChatMessage(
                    session_id=finished.id,
                    sender='user',
                    content='我先止损，再定位根因。',
                    is_good_response=False,
                    suggestion='补充量化结果。',
                ),
                ChatMessage(
                    session_id=finished.id,
                    sender='ai',
                    content='这是一条尚未得到回答的问题。',
                ),
            ])
            db.session.commit()

        with self.app.test_client() as client:
            login(client, self.teacher_id)
            response = client.get('/api/insights/weak-questions')

        self.assertEqual(response.status_code, 200)
        rows = response.get_json()['weak']
        self.assertEqual(len(rows), 1)
        self.assertIn('线上故障', rows[0]['question'])
        self.assertEqual(rows[0]['bad_rate'], 1.0)

    def test_next_round_request_is_idempotent(self):
        old = datetime.now() - timedelta(hours=1)
        with self.app.app_context():
            previous = InterviewSession(
                user_id=self.student_id,
                status='completed',
                round=1,
                reviewed=True,
                target_role='Python 工程师',
                start_time=old,
                end_time=old,
                last_activity=old,
            )
            db.session.add(previous)
            db.session.commit()
            previous_id = previous.id

        with self.app.test_client() as client:
            login(client, self.student_id)
            first = client.post(f'/api/interview/{previous_id}/next-round')
            second = client.post(f'/api/interview/{previous_id}/next-round')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(first.get_json()['session_id'], second.get_json()['session_id'])
        with self.app.app_context():
            self.assertEqual(
                InterviewSession.query.filter_by(parent_session_id=previous_id).count(),
                1,
            )

    def test_fresh_processing_report_is_not_reaped_from_old_chat_activity(self):
        old = datetime.now() - timedelta(hours=1)
        with self.app.app_context():
            report = InterviewSession(
                user_id=self.student_id,
                status='processing',
                target_role='Python 工程师',
                start_time=old,
                last_activity=old,
                end_time=datetime.now(),
            )
            db.session.add(report)
            db.session.commit()
            report_id = report.id

        with self.app.test_client() as client:
            login(client, self.student_id)
            response = client.get('/api/interview/processing-statuses')

        self.assertEqual(response.status_code, 200)
        self.assertIn(report_id, response.get_json()['processing'])
        with self.app.app_context():
            self.assertEqual(db.session.get(InterviewSession, report_id).status, 'processing')

    @patch('app.services.report_queue.Thread')
    @patch('app.services.report_queue._has_active_worker', return_value=False)
    @patch('app.services.report_queue._get_redis', return_value=object())
    def test_queue_falls_back_when_redis_has_no_worker(
        self,
        _redis,
        _worker_check,
        thread_class,
    ):
        from app.services.report_queue import enqueue_report

        result = enqueue_report(123)

        self.assertEqual(result['backend'], 'thread')
        thread_class.assert_called_once()
        thread_class.return_value.start.assert_called_once()


class SchemaMigrationTests(unittest.TestCase):
    def test_existing_database_receives_new_columns_and_unique_index(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'legacy.db'
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE interview_sessions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    status VARCHAR(20),
                    start_time DATETIME
                );
                CREATE TABLE chat_messages (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER
                );
                CREATE TABLE system_configs (
                    id INTEGER PRIMARY KEY,
                    "key" VARCHAR(50) UNIQUE NOT NULL,
                    value VARCHAR(255),
                    description VARCHAR(255),
                    updated_at DATETIME
                );
                """
            )
            connection.commit()
            connection.close()

            original_uri = Config.SQLALCHEMY_DATABASE_URI
            Config.SQLALCHEMY_DATABASE_URI = f'sqlite:///{database}'
            try:
                app = create_app()
                app.config.update(TESTING=True)
                with app.app_context():
                    inspector = sqlite3.connect(database)
                    session_columns = {
                        row[1]
                        for row in inspector.execute(
                            'PRAGMA table_info(interview_sessions)'
                        )
                    }
                    message_columns = {
                        row[1]
                        for row in inspector.execute('PRAGMA table_info(chat_messages)')
                    }
                    indexes = {
                        row[1]
                        for row in inspector.execute(
                            'PRAGMA index_list(interview_sessions)'
                        )
                    }
                    inspector.close()
            finally:
                Config.SQLALCHEMY_DATABASE_URI = original_uri

        self.assertTrue(
            {'last_activity', 'reviewed', 'abandoned', 'round', 'parent_session_id'}
            <= session_columns
        )
        self.assertIn('audio_urls', message_columns)
        self.assertIn('uq_interview_sessions_parent_session_id', indexes)


if __name__ == '__main__':
    unittest.main()
