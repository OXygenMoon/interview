"""
面试会话状态辅助：10min TTL 续接、冷却系统、复盘门槛。
被 routes.py 与 api/interview.py 共用，避免循环导入（本模块只依赖 db/models）。
"""
from datetime import datetime, timedelta
from sqlalchemy import func
from .. import db
from ..models import InterviewSession, SystemConfig


def _cfg_int(key, default):
    try:
        return int(SystemConfig.get(key, str(default)))
    except Exception:
        return default


def _cfg_bool(key, default):
    return SystemConfig.get(key, 'true' if default else 'false') == 'true'


def expire_stale_sessions(user_id):
    """把当前用户超过 TTL 仍 ongoing 的 session 标记为 expired + abandoned（懒清理，不删数据）。"""
    ttl = _cfg_int('session_ttl_minutes', 10)
    cutoff = datetime.now() - timedelta(minutes=ttl)
    stale = InterviewSession.query.filter(
        InterviewSession.user_id == user_id,
        InterviewSession.status == 'ongoing',
        InterviewSession.last_activity < cutoff,
    ).all()
    for s in stale:
        s.status = 'expired'
        s.abandoned = True
        if not s.end_time:
            s.end_time = s.last_activity or s.start_time
    if stale:
        db.session.commit()
    return len(stale)


def reap_stuck_reports(user_id):
    """把当前用户卡在 processing 过久的 session 标记为 failed（防 worker 崩溃后永久卡死）。"""
    timeout = _cfg_int('report_timeout_minutes', 15)
    cutoff = datetime.now() - timedelta(minutes=timeout)
    stuck = InterviewSession.query.filter(
        InterviewSession.user_id == user_id,
        InterviewSession.status == 'processing',
        func.coalesce(
            InterviewSession.end_time,
            InterviewSession.last_activity,
            InterviewSession.start_time,
        ) < cutoff,
    ).all()
    for s in stuck:
        s.status = 'failed'
        s.report_error = '报告任务执行超时，可重新提交生成。'
    if stuck:
        db.session.commit()
    return len(stuck)


def get_resumable_session(user_id):
    """返回当前用户可续接的 ongoing session（TTL 内仍存活），否则 None。"""
    expire_stale_sessions(user_id)
    return InterviewSession.query.filter(
        InterviewSession.user_id == user_id,
        InterviewSession.status == 'ongoing',
    ).order_by(InterviewSession.last_activity.desc()).first()


def mark_abandoned(session):
    """学生主动放弃某场进行中的面试。"""
    session.status = 'expired'
    session.abandoned = True
    session.end_time = datetime.now()
    db.session.commit()


def soft_delete_session(session, actor_id, reason='user_requested'):
    """Hide a session while retaining its report and transcript for recovery/audit."""
    if session.status == 'deleted':
        return False
    if session.status in ('ongoing', 'processing'):
        raise ValueError('进行中或正在生成报告的面试不能隐藏')
    session.status_before_delete = session.status
    session.status = 'deleted'
    session.deleted_at = datetime.now()
    session.deleted_by_id = actor_id
    session.deletion_reason = reason
    db.session.commit()
    return True


def restore_soft_deleted_session(session):
    """Restore a soft-deleted session to its prior state."""
    if session.status != 'deleted':
        return False
    session.status = session.status_before_delete or 'completed'
    session.deleted_at = None
    session.deleted_by_id = None
    session.deletion_reason = None
    session.status_before_delete = None
    db.session.commit()
    return True


def mark_reviewed(session):
    """学生查看过本次报告，满足复盘门槛。"""
    if not session.reviewed:
        session.reviewed = True
        db.session.commit()


def get_cooldown_status(user_id):
    """
    判断该用户能否开始新面试。
    reason: ok / abandon_cooldown / complete_cooldown / review_required / has_ongoing
    """
    expire_stale_sessions(user_id)
    reap_stuck_reports(user_id)
    last = InterviewSession.query.filter(
        InterviewSession.user_id == user_id,
    ).order_by(InterviewSession.last_activity.desc()).first()

    base = {'can_start': True, 'reason': 'ok', 'wait_seconds': 0,
            'last_session_id': None, 'last_session_status': None}
    if not last:
        return base
    base['last_session_id'] = last.id
    effective_status = (
        last.status_before_delete
        if last.status == 'deleted' and last.status_before_delete
        else last.status
    )
    base['last_session_status'] = effective_status

    now = datetime.now()
    ref_time = last.end_time or last.last_activity or last.start_time

    # 进行中：应去续接，不应新建
    if last.status == 'ongoing':
        base.update(can_start=False, reason='has_ongoing')
        return base

    # 放弃 / 过期：放弃罚时
    if last.abandoned or effective_status == 'expired':
        cd = _cfg_int('cooldown_abandon_minutes', 10)
        deadline = ref_time + timedelta(minutes=cd)
        if now < deadline:
            base.update(can_start=False, reason='abandon_cooldown',
                        wait_seconds=int((deadline - now).total_seconds()))
        return base

    # 已完成：先复盘，再冷却
    if effective_status in ('completed', 'processing'):
        if (last.status != 'deleted' and effective_status == 'completed'
                and _cfg_bool('cooldown_requires_review', True)
                and not last.reviewed):
            base.update(can_start=False, reason='review_required')
            return base
        cd = _cfg_int('cooldown_complete_minutes', 30)
        deadline = ref_time + timedelta(minutes=cd)
        if now < deadline:
            base.update(can_start=False, reason='complete_cooldown',
                        wait_seconds=int((deadline - now).total_seconds()))
        return base

    return base
