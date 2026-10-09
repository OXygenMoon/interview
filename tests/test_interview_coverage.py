"""Plan topics without repetition; ending remains available at every point."""

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
from app.services.interview_coverage import DIMENSIONS, dimension_answers, missing_dimensions, required_questions, closing_response


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
    assert '下一道计划题：' + required_questions(difficulty, round_num)['抗压能力'] in system


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


def test_empty_interview_can_end_and_generate_an_evidence_note():
    with patch.object(ai_agent.client.chat.completions, 'create') as create:
        report = ai_agent.generate_interview_report([], '文员')
    create.assert_not_called()
    assert report['overall']['evaluated_dimensions'] == []


def test_early_ended_interview_with_answers_can_generate_a_report():
    history = paired_history('新手模式')[:2]
    overall = {
        'scores': dict(zip(DIMENSIONS, [92, 0, 92, 0, 0])),
        'evaluated_dimensions': ['专业技能', '语言表达'],
        'total_score': 60, 'comment': '本轮提前结束，仅评已展示内容。',
    }
    details = {'reviews': [{'suggestion': '回答相关。', 'reference': '示例。', 'is_good': True}]}
    responses = [SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(p)))])
                 for p in [overall, details]]
    with patch.object(ai_agent.client.chat.completions, 'create', side_effect=responses):
        report = ai_agent.generate_interview_report(history, '文员', difficulty='新手模式')
    assert len(report['details_list']) == 1
    assert report['overall']['evaluated_dimensions'] == ['专业技能', '语言表达']


def test_screenshot_clarification_keeps_the_original_task_question():
    history = [
        ('ai', required_questions('新手模式')['逻辑思维']),
        ('user', '1'),
        ('ai', '我没太理解你的意思，是说“1”表示继续，还是想回答这道题呢？可以简单说一下你想表达什么。'),
        ('user', '如果说给我一项任务，我会先去了解这个任务的一个目标，再去实操。'),
        ('ai', '好的，了解目标再动手，这个思路可以。那这个岗位平时主要做什么？请说出一项你了解的工作。'),
    ]
    history = [SimpleNamespace(sender=s, content=c) for s, c in history]
    assert '逻辑思维' not in missing_dimensions(history, '新手模式')
    assert '专业技能' in missing_dimensions(history, '新手模式')
    evidence = dimension_answers(history, '新手模式')['逻辑思维']
    assert evidence['answer'].endswith('再去实操。')
    assert '小任务' in evidence['question']


@pytest.mark.parametrize('difficulty', ['新手模式', '标准模式', '压力模式'])
def test_program_advances_through_the_plan_without_extra_model_questions(difficulty):
    history = [SimpleNamespace(sender='ai', content='你好，请介绍自己。'),
               SimpleNamespace(sender='user', content='我学习过办公软件，想做文员。')]
    with patch.object(ai_agent.client.chat.completions, 'create') as create:
        for question in required_questions(difficulty).values():
            reply = ai_agent.get_ai_response(history, difficulty=difficulty)
            assert question in reply
            assert ''.join(ai_agent.stream_ai_response(history, difficulty=difficulty)) == reply
            history.extend([SimpleNamespace(sender='ai', content=reply),
                            SimpleNamespace(sender='user', content='先看要求，再沟通和执行。')])
        assert '点击“结束面试”查看报告' in ai_agent.get_ai_response(history, difficulty=difficulty)
    create.assert_not_called()


def test_clarified_task_answer_advances_to_pressure_instead_of_repeating_logic():
    history = [SimpleNamespace(sender=s, content=c) for s, c in [
        ('ai', '这个岗位平时主要做什么？'), ('user', '整理文件和录入资料。'),
        ('ai', '如果要完成一项岗位相关的小任务，你会先做什么、再做什么？'), ('user', '1'),
        ('ai', '我没太理解你的意思，是说“1”表示继续，还是想回答这道题呢？'),
        ('user', '我会先了解任务的目标，再去实操。'),
    ]]
    with patch.object(ai_agent.client.chat.completions, 'create') as create:
        reply = ai_agent.get_ai_response(history, difficulty='新手模式')
    create.assert_not_called()
    assert required_questions('新手模式')['抗压能力'] in reply


def test_paraphrased_questions_and_omitted_hints_are_not_repeated():
    questions = [
        '你了解这个岗位的主要职责吗？',
        '接到任务以后，你打算按什么顺序做？',
        '时间很紧，实训任务做不完时怎么办？',
        '用自己的话简单介绍这份工作的内容。',
        '怎样礼貌地向同学确认资料？',
    ]
    history = [SimpleNamespace(sender=s, content=c) for q in questions
               for s, c in [('ai', q), ('user', '我会先看要求，再沟通和行动。')]]
    assert missing_dimensions(history, '新手模式') == []
    assert closing_response(history, '新手模式') is not None


@pytest.mark.parametrize('difficulty', ['新手模式', '标准模式', '压力模式'])
def test_last_planned_answer_gets_a_closing_in_both_chat_paths(difficulty):
    history = paired_history(difficulty)
    with patch.object(ai_agent.client.chat.completions, 'create') as create:
        plain = ai_agent.get_ai_response(history, difficulty=difficulty)
        streamed = ''.join(ai_agent.stream_ai_response(history, difficulty=difficulty))
    create.assert_not_called()
    assert plain == streamed
    assert '点击“结束面试”查看报告' in plain


@pytest.mark.parametrize('answer', ['请结束面试', '我想结束这场面试', '我无法继续了'])
def test_explicit_end_request_does_not_trigger_another_question(answer):
    history = [SimpleNamespace(sender='user', content=answer)]
    with patch.object(ai_agent.client.chat.completions, 'create') as create:
        assert '面试结束' in ai_agent.get_ai_response(history)
    create.assert_not_called()


@pytest.mark.parametrize('answer', ['我的介绍结束了，谢谢', '项目结束后我整理了文件', '客户说他想结束面试'])
def test_end_keywords_in_an_answer_do_not_end_the_interview(answer):
    assert closing_response([SimpleNamespace(sender='user', content=answer)], '新手模式') is None


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


def test_live_chat_persists_the_planned_questions_then_closes_without_repeating(coverage_app):
    with coverage_app.app_context():
        db.session.add(ChatMessage(session_id=1, sender='ai', content='你好，请介绍自己。',
                                   generation_status='completed'))
        db.session.commit()
    with coverage_app.test_client() as client, patch.object(
        ai_agent.client.chat.completions, 'create',
    ) as create, patch('app.services.tts_service.text_to_speech_chunks', return_value=iter([])):
        with client.session_transaction() as session:
            session['_user_id'] = '1'
        answers = ['我学过办公软件。', '整理文件、录入资料。', '先看目标，再动手。',
                   '先完成重要部分，再向老师说明和求助。', '文员负责整理和记录资料。',
                   '你好，我想确认一下这份资料，方便帮我看一下吗？']
        replies = []
        for answer in answers:
            response = client.post('/api/interview/1/chat', json={'message': answer})
            assert response.status_code == 200
            events = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
                      if line.startswith('data: ')]
            assert not any(event['type'] == 'error' for event in events)
            replies.append(''.join(event['content'] for event in events if event['type'] == 'token'))
        create.assert_not_called()
        for reply, question in zip(replies, required_questions('新手模式').values()):
            assert question in reply
        assert '点击“结束面试”查看报告' in replies[-1]
        with coverage_app.app_context():
            history = ChatMessage.query.filter_by(session_id=1).order_by(ChatMessage.id).all()
            assert missing_dimensions(history, '新手模式') == []
            count = len(history)
        with patch('app.services.report_queue.enqueue_report', return_value={'backend': 'thread'}):
            assert client.post('/api/interview/1/finish').status_code == 200
        with coverage_app.app_context():
            assert ChatMessage.query.filter_by(session_id=1).count() == count


@pytest.mark.parametrize('status', ['ongoing', 'failed', 'expired'])
def test_finish_never_inserts_questions_and_queues_once_even_when_incomplete(coverage_app, status):
    with coverage_app.app_context():
        db.session.get(InterviewSession, 1).status = status
        db.session.commit()
    with coverage_app.test_client() as client, patch('app.services.report_queue.enqueue_report', return_value={
        'backend': 'thread', 'durable': False,
    }) as enqueue:
        with client.session_transaction() as session:
            session['_user_id'] = '1'
        response = client.post('/api/interview/1/finish')
        assert response.status_code == 200
        assert response.json['status'] == 'processing'
        enqueue.assert_called_once()
        with coverage_app.app_context():
            assert db.session.get(InterviewSession, 1).status == 'processing'
            assert ChatMessage.query.filter_by(session_id=1).count() == 0
        assert client.post('/api/interview/1/finish').json['status'] == 'already_finished'
        enqueue.assert_called_once()
