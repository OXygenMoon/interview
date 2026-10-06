"""Read-only learning statistics for a server-authenticated linked WikiBook user."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import db
from ..integrations.account_link import LinkError, user_identity
from ..models import (AccountLink, ChatMessage, InterviewSession, LearningAttempt,
                      LearningMaterial, User, UserLearningProgress)


SCHEMA_VERSION = 1
MIN_ANSWERS = 3
BEIJING = timezone(timedelta(hours=8))


def now_beijing():
    return datetime.now(BEIJING).replace(tzinfo=None)


def _window_bound(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise LinkError('统计日期格式无效。')
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        raise LinkError('统计日期格式无效。') from None


def _beijing(value, stored_timezone):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=stored_timezone)
    return value.astimezone(BEIJING).replace(tzinfo=None)


def linked_learning_achievements(wikibook_user_id, data):
    """Bounds are Beijing midnights, start inclusive and end exclusive.

    Fetch antecedent sessions/attempts before filtering completion events, so
    a chain or recovery can start before the requested activity window.
    """
    from flask import current_app

    start = _window_bound(data.get('start_date'))
    end = _window_bound(data.get('end_date_exclusive'))
    if start and end and start >= end:
        raise LinkError('统计开始日期必须早于结束日期。')
    now = now_beijing()
    stored_timezone = ZoneInfo(current_app.config.get('INTERVIEW_RECORD_TIMEZONE', 'Asia/Shanghai'))

    def in_window(value):
        return bool(value and value <= now and (not start or value >= start)
                    and (not end or value < end))

    result = {'schema_version': SCHEMA_VERSION, 'wikibook_user_id': wikibook_user_id,
              'linked': False, 'link_id': None, 'generated_at': now.isoformat() + '+08:00',
              'metrics': {}, 'valid_days': []}
    link = AccountLink.query.filter_by(wikibook_user_id=wikibook_user_id).first()
    if link is None:
        return result
    user_identity(db.session.get(User, link.interview_user_id))
    result.update(linked=True, link_id=link.id)
    sessions = InterviewSession.query.filter_by(user_id=link.interview_user_id).all()
    candidates = {s.id: s for s in sessions
                  if s.status == 'completed' and not s.deleted_at and not s.abandoned and not s.report_error
                  and s.evaluation_source != 'rule' and s.total_score is not None
                  and (s.summary_comment or '').strip()
                  and s.start_time and s.end_time
                  and _beijing(s.start_time, stored_timezone) <= _beijing(s.end_time, stored_timezone) <= now}
    # Only successfully generated questions and answers in this user's sessions
    # are read. One question can contribute at most one answer, even if duplicate
    # user messages were imported. No transcript is returned to WikiBook.
    question_for_session = {}
    answered_questions = defaultdict(set)
    messages = ChatMessage.query.join(InterviewSession).filter(
        InterviewSession.user_id == link.interview_user_id,
        InterviewSession.status == 'completed',
        ChatMessage.generation_status == 'completed',
    ).order_by(ChatMessage.timestamp, ChatMessage.id).all()
    for message in messages:
        session = candidates.get(message.session_id)
        when = _beijing(message.timestamp, stored_timezone)
        if (session is None or not when or not (message.content or '').strip()
                or not _beijing(session.start_time, stored_timezone) <= when <= _beijing(session.end_time, stored_timezone)):
            continue
        if message.sender == 'ai':
            question_for_session[session.id] = message.id
        elif message.sender == 'user' and session.id in question_for_session:
            answered_questions[session.id].add(question_for_session[session.id])
    valid = {sid: session for sid, session in candidates.items()
             if len(answered_questions[sid]) >= MIN_ANSWERS}
    window_sessions = [s for s in valid.values() if in_window(_beijing(s.end_time, stored_timezone))]
    days = sorted({_beijing(s.end_time, stored_timezone).date().isoformat() for s in window_sessions})
    chains = set()
    for third in window_sessions:
        if third.round != 3:
            continue
        second = valid.get(third.parent_session_id)
        first = valid.get(second.parent_session_id) if second else None
        if (not second or not first or second.round != 2 or first.round != 1
                or first.parent_session_id is not None
                or not first.position_id or first.position_id != second.position_id
                or first.position_id != third.position_id):
            continue
        times = [_beijing(s.end_time, stored_timezone) for s in (first, second, third)]
        if (times[0] <= _beijing(second.start_time, stored_timezone)
                and times[1] <= _beijing(third.start_time, stored_timezone)):
            chains.add(first.id)

    # Material type is authoritative: article completion also stores score=100.
    quiz_progress = db.session.query(UserLearningProgress).join(
        LearningMaterial, LearningMaterial.id == UserLearningProgress.material_id,
    ).filter(UserLearningProgress.user_id == link.interview_user_id,
             UserLearningProgress.status == 'completed',
             LearningMaterial.material_type == 'quiz').all()
    attempts = db.session.query(LearningAttempt).join(
        LearningMaterial, LearningMaterial.id == LearningAttempt.material_id,
    ).filter(LearningAttempt.user_id == link.interview_user_id,
             LearningMaterial.material_type == 'quiz').order_by(
                 LearningAttempt.attempted_at, LearningAttempt.id).all()
    passed = set()
    recovered = set()
    failed_before = set()
    first_pass = {}
    legacy_pass = {p.material_id: _beijing(p.completed_at, stored_timezone)
                   for p in quiz_progress if type(p.score) is int and 80 <= p.score <= 100
                   and p.completed_at and _beijing(p.completed_at, stored_timezone) <= now}
    for attempt in attempts:
        when = _beijing(attempt.attempted_at, stored_timezone)
        if not when or when > now:
            continue
        if type(attempt.score) is not int:
            continue
        if attempt.passed and 80 <= attempt.score <= 100:
            if attempt.material_id not in first_pass:
                first_pass[attempt.material_id] = when
                previous = legacy_pass.get(attempt.material_id)
                if in_window(when) and not (previous and previous < when):
                    passed.add(attempt.material_id)
                    if attempt.material_id in failed_before:
                        recovered.add(attempt.material_id)
        elif not attempt.passed and 0 <= attempt.score < 80:
            failed_before.add(attempt.material_id)
    for material_id, when in legacy_pass.items():
        if in_window(when) and (material_id not in first_pass or when < first_pass[material_id]):
            passed.add(material_id)

    result['valid_days'] = days
    result['metrics'] = {
        'interview_valid_session_count': len(window_sessions),
        'interview_active_day_count': len(days),
        'interview_report_viewed_count': sum(bool(s.reviewed) for s in window_sessions),
        'interview_round_chain_complete_count': len(chains),
        'interview_position_variety_count': len({s.position_id for s in window_sessions if s.position_id}),
        'interview_quiz_passed_count': len(passed),
        'interview_quiz_recovery_count': len(recovered),
    }
    return result


def notify_wikibook_learning_change(interview_user_id):
    """Best-effort after-commit wakeup; collection views also repair missed awards."""
    from flask import current_app
    from ..integrations.account_link import enabled, server_call

    if not enabled():
        return
    try:
        link = AccountLink.query.filter_by(interview_user_id=interview_user_id).first()
        if link is not None:
            server_call('wikibook', '/internal/account-link/reward-scan',
                        {'user_id': link.wikibook_user_id}, timeout=(1, 2))
    except Exception:
        # Never log remote error bodies or roll back the committed learning action.
        current_app.logger.warning('WikiBook reward notification unavailable; collection refresh will retry')
