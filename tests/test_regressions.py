import os
import json
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
from app.models import (
    ChatMessage,
    Company,
    InterviewSession,
    LearningAttempt,
    LearningCategory,
    LearningMaterial,
    Position,
    RandomPracticeAttempt,
    Resume,
    User,
    UserLearningProgress,
)
from app.services.ai_agent import AIServiceError
from app.utils.session_state import get_cooldown_status


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
            self.admin = User(username='admin', role='admin')
            self.student.set_password('test')
            self.teacher.set_password('test')
            self.admin.set_password('test')
            db.session.add_all([self.student, self.teacher, self.admin])
            db.session.commit()
            self.student_id = self.student.id
            self.teacher_id = self.teacher.id
            self.admin_id = self.admin.id

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

    def test_failed_quiz_is_recorded_but_remains_retryable(self):
        with self.app.app_context():
            category = LearningCategory(name='基础')
            db.session.add(category)
            db.session.flush()
            material = LearningMaterial(
                category_id=category.id,
                title='测验',
                material_type='quiz',
                content=json.dumps([
                    {
                        'id': 1,
                        'title': '题目一',
                        'answer': 'A',
                        'options': [{'key': 'A', 'val': '对'}, {'key': 'B', 'val': '错'}],
                    },
                    {
                        'id': 2,
                        'title': '题目二',
                        'answer': 'A',
                        'options': [{'key': 'A', 'val': '对'}, {'key': 'B', 'val': '错'}],
                    },
                ]),
            )
            db.session.add(material)
            db.session.commit()
            material_id = material.id

        with self.app.test_client() as client:
            login(client, self.student_id)
            failed = client.post(
                f'/learning/submit_quiz/{material_id}',
                data={'q_1': 'A', 'q_2': 'B'},
            )
            passed = client.post(
                f'/learning/submit_quiz/{material_id}',
                data={'q_1': 'A', 'q_2': 'A'},
            )

        self.assertEqual(failed.status_code, 302)
        self.assertEqual(passed.status_code, 302)
        with self.app.app_context():
            attempts = LearningAttempt.query.order_by(LearningAttempt.id).all()
            self.assertEqual([attempt.score for attempt in attempts], [50, 100])
            self.assertEqual([attempt.passed for attempt in attempts], [False, True])
            progress = UserLearningProgress.query.filter_by(
                user_id=self.student_id,
                material_id=material_id,
            ).one()
            self.assertEqual(progress.score, 100)

    def test_soft_delete_preserves_transcript_and_admin_can_restore(self):
        with self.app.app_context():
            interview = InterviewSession(
                user_id=self.student_id,
                status='completed',
                total_score=88,
            )
            db.session.add(interview)
            db.session.flush()
            db.session.add(ChatMessage(
                session_id=interview.id,
                sender='user',
                content='保留这条回答',
            ))
            db.session.commit()
            interview_id = interview.id

        with self.app.test_client() as client:
            login(client, self.admin_id)
            deleted = client.post(f'/api/admin/interview/delete/{interview_id}')
            restored = client.post(f'/api/admin/interview/restore/{interview_id}')

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(restored.status_code, 200)
        with self.app.app_context():
            interview = db.session.get(InterviewSession, interview_id)
            self.assertEqual(interview.status, 'completed')
            self.assertEqual(
                ChatMessage.query.filter_by(session_id=interview_id).count(),
                1,
            )

    def test_hidden_session_keeps_cooldown_and_processing_cannot_be_hidden(self):
        with self.app.app_context():
            completed = InterviewSession(
                user_id=self.student_id,
                status='completed',
                reviewed=True,
                end_time=datetime.now(),
                last_activity=datetime.now(),
            )
            processing = InterviewSession(
                user_id=self.student_id,
                status='processing',
                end_time=datetime.now() - timedelta(minutes=1),
                last_activity=datetime.now() + timedelta(seconds=1),
            )
            db.session.add_all([completed, processing])
            db.session.commit()
            completed_id = completed.id
            processing_id = processing.id

        with self.app.test_client() as client:
            login(client, self.admin_id)
            blocked = client.post(
                f'/api/admin/interview/delete/{processing_id}',
            )

        self.assertEqual(blocked.status_code, 409)
        with self.app.app_context():
            processing = db.session.get(InterviewSession, processing_id)
            processing.last_activity = datetime.now() - timedelta(minutes=20)
            db.session.commit()

        with self.app.test_client() as client:
            login(client, self.admin_id)
            hidden = client.post(
                f'/api/admin/interview/delete/{completed_id}',
            )

        self.assertEqual(hidden.status_code, 200)
        with self.app.app_context():
            cooldown = get_cooldown_status(self.student_id)
            self.assertFalse(cooldown['can_start'])
            self.assertEqual(cooldown['reason'], 'complete_cooldown')

    def test_deactivate_student_keeps_business_data_and_blocks_login(self):
        with self.app.app_context():
            db.session.add(InterviewSession(
                user_id=self.student_id,
                status='completed',
                total_score=75,
            ))
            db.session.commit()

        with self.app.test_client() as client:
            login(client, self.admin_id)
            response = client.post(f'/api/admin/student/delete/{self.student_id}')
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertFalse(student.active)
            self.assertEqual(
                InterviewSession.query.filter_by(user_id=self.student_id).count(),
                1,
            )

        with self.app.test_client() as client:
            response = client.post('/login', data={
                'username': 'student',
                'password': 'test',
            })
            self.assertIn('已停用'.encode('utf-8'), response.data)

    def test_forced_password_change_clears_flag(self):
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            student.must_change_password = True
            db.session.commit()

        with self.app.test_client() as client:
            response = client.post('/login', data={
                'username': 'student',
                'password': 'test',
            })
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith('/change-password'))
            changed = client.post('/change-password', data={
                'current_password': 'test',
                'new_password': 'a-secure-password',
                'confirm_password': 'a-secure-password',
            })
            self.assertEqual(changed.status_code, 302)

        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertFalse(student.must_change_password)
            self.assertTrue(student.check_password('a-secure-password'))

    @patch('app.api.interview.evaluate_random_answer')
    def test_random_ai_failure_is_not_saved_as_score(self, evaluate):
        evaluate.side_effect = AIServiceError('provider down')
        with self.app.app_context():
            from app.services.question_bank import get_random_interview_questions
            question = get_random_interview_questions()[0]

        with self.app.test_client() as client:
            login(client, self.student_id)
            response = client.post('/api/interview/random/evaluate', json={
                'question': question,
                'answer': '这是我的回答。',
            })

        self.assertEqual(response.status_code, 503)
        with self.app.app_context():
            attempt = RandomPracticeAttempt.query.one()
            self.assertEqual(attempt.status, 'evaluation_failed')
            self.assertIsNone(attempt.score)

    def test_create_session_freezes_position_and_resume(self):
        with self.app.app_context():
            company = Company(name='示例公司', description='公司快照')
            db.session.add(company)
            db.session.flush()
            position = Position(
                company_id=company.id,
                name='后端工程师',
                description='岗位快照',
            )
            resume = Resume(
                user_id=self.student_id,
                title='面试简历',
                content={
                    'basic': {'name': '学生', 'job_target': '后端工程师'},
                    'skills': ['Python'],
                },
            )
            student = db.session.get(User, self.student_id)
            student.resume_text = '当前简历不得被覆盖'
            db.session.add_all([position, resume])
            db.session.commit()
            position_id = position.id
            resume_id = resume.id

        with self.app.test_client() as client:
            login(client, self.student_id)
            response = client.post('/api/interview/create', data={
                'target_role': '客户端伪造岗位',
                'position_id': str(position_id),
                'resume_id': str(resume_id),
                'difficulty': '标准模式',
            })

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            interview = InterviewSession.query.one()
            self.assertEqual(interview.target_role, '后端工程师')
            self.assertEqual(interview.position_snapshot['company_name'], '示例公司')
            self.assertIn('Python', interview.resume_snapshot)
            self.assertEqual(interview.resume_id, resume_id)
            self.assertEqual(
                db.session.get(User, self.student_id).resume_text,
                '当前简历不得被覆盖',
            )

    def test_growth_returns_most_recent_twenty(self):
        base = datetime.now() - timedelta(days=30)
        with self.app.app_context():
            for index in range(25):
                db.session.add(InterviewSession(
                    user_id=self.student_id,
                    status='completed',
                    total_score=index,
                    start_time=base + timedelta(days=index),
                ))
            db.session.commit()

        with self.app.test_client() as client:
            login(client, self.student_id)
            data = client.get('/api/insights/growth').get_json()

        self.assertEqual(len(data['points']), 20)
        self.assertEqual(data['points'][0]['total'], 5)
        self.assertEqual(data['points'][-1]['total'], 24)
        self.assertNotIn('predict_next', data)

    def test_compare_keeps_same_named_classes_separate_by_department(self):
        with self.app.app_context():
            other = User(
                username='other',
                role='student',
                department='设计系',
                class_name='软件一班',
            )
            other.set_password('test')
            student = db.session.get(User, self.student_id)
            student.department = '计算机系'
            db.session.add(other)
            db.session.flush()
            db.session.add_all([
                InterviewSession(
                    user_id=student.id,
                    status='completed',
                    total_score=80,
                    radar_data={'专业技能': 80},
                ),
                InterviewSession(
                    user_id=other.id,
                    status='completed',
                    total_score=60,
                    radar_data={'专业技能': 60},
                ),
            ])
            db.session.commit()

        with self.app.test_client() as client:
            login(client, self.admin_id)
            data = client.get('/api/insights/compare').get_json()

        self.assertEqual(len(data['classes']), 2)
        self.assertEqual(
            {row['department'] for row in data['classes']},
            {'计算机系', '设计系'},
        )

    @patch('app.services.ai_agent.client.chat.completions.create')
    def test_report_provider_failure_raises_instead_of_returning_sixty(self, create):
        create.side_effect = RuntimeError('provider down')
        from app.services.ai_agent import _get_overall_score

        with self.assertRaises(AIServiceError):
            _get_overall_score('面试记录', '后端工程师', 3)

    def test_csrf_rejects_missing_token(self):
        previous_testing = self.app.config['TESTING']
        self.app.config.update(TESTING=False, CSRF_ENABLED=True)
        try:
            with self.app.test_client() as client:
                client.get('/login')
                missing = client.post('/login', data={
                    'username': 'nobody',
                    'password': 'invalid',
                })
                with client.session_transaction() as session:
                    token = session['_csrf_token']
                valid = client.post('/login', data={
                    'csrf_token': token,
                    'username': 'nobody',
                    'password': 'invalid',
                })
        finally:
            self.app.config['TESTING'] = previous_testing

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(valid.status_code, 200)

    def test_health_probe_and_security_headers(self):
        with self.app.test_client() as client:
            response = client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['database'], 'ok')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'SAMEORIGIN')

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
                    session_id INTEGER,
                    audio_urls TEXT
                );
                INSERT INTO chat_messages (id, session_id, audio_urls)
                VALUES (1, 1, 'null');
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
                    null_audio_rows = inspector.execute(
                        'SELECT count(*) FROM chat_messages '
                        'WHERE audio_urls IS NOT NULL'
                    ).fetchone()[0]
                    inspector.close()
            finally:
                Config.SQLALCHEMY_DATABASE_URI = original_uri

        self.assertTrue(
            {'last_activity', 'reviewed', 'abandoned', 'round', 'parent_session_id'}
            <= session_columns
        )
        self.assertIn('audio_urls', message_columns)
        self.assertIn('uq_interview_sessions_parent_session_id', indexes)
        self.assertEqual(null_audio_rows, 0)


if __name__ == '__main__':
    unittest.main()
