"""Missing questions must be collected before a five-dimensional report is queued."""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app import create_app, db
from app.config import Config
from app.models import ChatMessage, InterviewSession, User
from app.services import ai_agent
from app.services.interview_coverage import DIMENSIONS, dimension_answers, missing_dimensions, required_questions


def paired_history(difficulty, round_num=1):
    answers = {
        '专业技能': '整理文件和录入资料。',
        '逻辑思维': '先看要求，再整理资料。',
        '抗压能力': '先完成重要部分，再告诉老师进度，请老师帮我确认剩下的任务。',
        '语言表达': '文员负责整理和记录资料，让大家方便查找。',
        '礼仪态度': '你好，我想确认一下这份资料的日期，方便帮我看一下吗？谢谢。',
    }
    return [SimpleNamespace(sender=sender, content=content, generation_status='completed')
            for dimension, question in required_questions(difficulty, round_num).items()
            for sender, content in [('ai', question), ('user', answers[dimension])]]


@pytest.mark.parametrize('difficulty', ['新手模式', '标准模式', '压力模式'])
@pytest.mark.parametrize('round_num', [1, 2, 3])
def test_all_rounds_collect_five_actual_answers(difficulty, round_num):
    history = paired_history(difficulty, round_num)
    assert missing_dimensions(history[:-1], difficulty, round_num) == ['礼仪态度']
    assert missing_dimensions(history, difficulty, round_num) == []
    assert set(dimension_answers(history, difficulty, round_num)) == set(DIMENSIONS)
    system = ai_agent._build_interview_messages(history[:4], '文员', difficulty, '', '', round_num)[0]['content']
    assert '下一道必答题：' + required_questions(difficulty, round_num)['抗压能力'] in system


@pytest.mark.parametrize('answer', ['谢谢', '结束面试', '什么意思', '请再说一遍'])
def test_clarifications_and_endings_do_not_complete_a_dimension(answer):
    history = paired_history('新手模式')[:2]
    history[-1].content = answer
    assert len(missing_dimensions(history, '新手模式')) == 5


def test_candidate_claims_incomplete_questions_and_unanswered_prompts_do_not_count():
    history = paired_history('标准模式')
    history[4].generation_status = 'interrupted'
    assert missing_dimensions(history, '标准模式') == ['抗压能力']
    history[4].sender = 'user'
    history[4].generation_status = 'completed'
    assert missing_dimensions(history, '标准模式') == ['抗压能力']
    history = paired_history('标准模式')[:1]
    assert len(missing_dimensions(history, '标准模式')) == 5
    history.append(SimpleNamespace(sender='user', content='不知道', generation_status='completed'))
    assert '专业技能' not in missing_dimensions(history, '标准模式')


def test_completed_report_cannot_omit_pressure_even_if_the_model_does():
    history = paired_history('新手模式')
    transcript = json.dumps([{'sender': m.sender, 'content': m.content} for m in history], ensure_ascii=False)
    payload = {
        'scores': dict(zip(DIMENSIONS, [95, 95, 95, 0, 95])),
        'evaluated_dimensions': ['专业技能', '逻辑思维', '语言表达', '礼仪态度'],
        'total_score': 95, 'comment': '抗压未评估。',
    }
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])
    with patch.object(ai_agent.client.chat.completions, 'create', return_value=response) as create:
        with pytest.raises(ai_agent.AIServiceError):
            ai_agent._get_overall_score(transcript, '文员', 5, difficulty='新手模式')
    messages = create.call_args.kwargs['messages']
    assert '五维已完成，必须全部评分' in messages[0]['content']
    assert set(json.loads(messages[1]['content'])['required_dimension_evidence']) == set(DIMENSIONS)


def test_worker_does_not_generate_a_report_for_incomplete_new_interviews():
    with patch.object(ai_agent.client.chat.completions, 'create') as create:
        with pytest.raises(ai_agent.AIServiceError):
            ai_agent.generate_interview_report(paired_history('标准模式')[:4], '文员', require_complete=True)
    create.assert_not_called()


@pytest.fixture
def coverage_app(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path / "coverage.db"}')
    app = create_app()
    app.config.update(TESTING=True, CSRF_ENABLED=False, SESSION_COOKIE_SECURE=False)
    with app.app_context():
        db.create_all()
        db.session.add(User(id=1, username='coverage-student', role='student'))
        db.session.add(InterviewSession(id=1, user_id=1, target_role='文员', difficulty='新手模式', status='ongoing'))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()


@pytest.mark.parametrize('status', ['ongoing', 'failed', 'expired'])
def test_finish_supplements_each_missing_question_then_queues_once(coverage_app, status):
    with coverage_app.app_context():
        db.session.get(InterviewSession, 1).status = status
        db.session.commit()
    with coverage_app.test_client() as client, patch('app.services.report_queue.enqueue_report', return_value={
        'backend': 'thread', 'durable': False,
    }) as enqueue:
        with client.session_transaction() as session:
            session['_user_id'] = '1'
        for dimension, question in required_questions('新手模式').items():
            response = client.post('/api/interview/1/finish')
            assert response.status_code == 409
            assert response.json['status'] == 'coverage_required'
            assert response.json['missing_dimensions'][0] == dimension
            enqueue.assert_not_called()
            with coverage_app.app_context():
                interview = db.session.get(InterviewSession, 1)
                assert interview.status == 'ongoing'
                assert interview.total_score is None
                count = ChatMessage.query.filter_by(session_id=1).count()
            assert client.post('/api/interview/1/finish').status_code == 409
            with coverage_app.app_context():
                assert ChatMessage.query.filter_by(session_id=1).count() == count
                assert question in ChatMessage.query.order_by(ChatMessage.id.desc()).first().content
                db.session.add(ChatMessage(session_id=1, sender='user', content='先看要求，再沟通和处理。',
                                           generation_status='completed'))
                db.session.commit()
        assert client.post('/api/interview/1/finish').json['status'] == 'processing'
        enqueue.assert_called_once()
        assert client.post('/api/interview/1/finish').json['status'] == 'already_finished'
        enqueue.assert_called_once()
