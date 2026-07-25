"""Durable RQ-backed interview report queue with explicit local fallback."""

import logging
import os
import socket
import time
import uuid
from datetime import datetime, timedelta
from threading import Thread
from time import monotonic

from ..config import Config


logger = logging.getLogger(__name__)

SUPPORTED_MODES = {'auto', 'rq', 'thread'}
REDIS_CHECK_TTL_SECONDS = 5

_redis_client = None
_redis_checked_at = 0.0


class ReportQueueError(RuntimeError):
    """Base exception for queue configuration and enqueue failures."""


class ReportQueueUnavailable(ReportQueueError):
    """Raised when durable queue mode cannot reach Redis."""


def _queue_mode():
    mode = str(Config.REPORT_QUEUE_MODE or '').strip().lower()
    if mode not in SUPPORTED_MODES:
        raise ReportQueueError(
            f'无效 REPORT_QUEUE_MODE={mode!r}，应为 auto、rq 或 thread'
        )
    return mode


def _retry_intervals():
    raw = str(Config.REPORT_RETRY_INTERVALS or '').strip()
    if not raw:
        return ()
    try:
        intervals = tuple(
            int(value.strip())
            for value in raw.split(',')
            if value.strip()
        )
    except ValueError as exc:
        raise ReportQueueError(
            'REPORT_RETRY_INTERVALS 必须是逗号分隔的整数秒数'
        ) from exc
    if any(interval < 0 for interval in intervals):
        raise ReportQueueError('REPORT_RETRY_INTERVALS 不能包含负数')
    return intervals


def _get_redis(force=False):
    """Return a recently verified Redis connection or ``None``."""
    global _redis_client, _redis_checked_at

    now = monotonic()
    if (
        not force
        and _redis_checked_at
        and now - _redis_checked_at < REDIS_CHECK_TTL_SECONDS
    ):
        return _redis_client

    _redis_checked_at = now
    try:
        import redis

        client = redis.from_url(
            Config.REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        client.ping()
        _redis_client = client
    except Exception as exc:
        logger.warning('Redis queue probe failed: %s', exc)
        _redis_client = None
    return _redis_client


def reset_check():
    """Reset Redis probe cache for tests and operator-triggered rechecks."""
    global _redis_client, _redis_checked_at
    _redis_client = None
    _redis_checked_at = 0.0


def _queue(client):
    from rq import Queue

    return Queue(Config.REPORT_QUEUE_NAME, connection=client)


def _active_workers(client):
    try:
        from rq import Worker

        return Worker.all(connection=client, queue=_queue(client))
    except Exception as exc:
        logger.warning('RQ worker probe failed: %s', exc)
        return []


def _has_active_worker(client):
    return bool(_active_workers(client))


def is_rq_available():
    client = _get_redis()
    return client is not None and _has_active_worker(client)


def _thread_runner(fn, session_id):
    try:
        fn(session_id)
    except Exception:
        logger.exception('Local report thread failed for session %s', session_id)


def _enqueue_thread(task, session_id, defer_start=False):
    thread = Thread(
        target=_thread_runner,
        args=(task, session_id),
        daemon=True,
        name=f'interview-report-{session_id}',
    )
    result = {
        'job_id': None,
        'backend': 'thread',
        'worker_available': True,
        'durable': False,
    }
    if defer_start:
        result['_start'] = thread.start
    else:
        thread.start()
    return result


def enqueue_report(session_id, submission_count=1, defer_thread_start=False):
    """Enqueue one report generation submission.

    ``rq`` mode never falls back to a process-local thread. Jobs remain queued
    in Redis while workers are temporarily offline. ``auto`` mode is intended
    for development and uses a thread only when no active RQ worker exists.
    """
    try:
        from ..api.interview import background_report_task
    except Exception as exc:
        raise ReportQueueError(f'无法加载报告任务: {exc}') from exc

    mode = _queue_mode()
    if mode == 'thread':
        return _enqueue_thread(
            background_report_task,
            session_id,
            defer_start=defer_thread_start,
        )

    client = _get_redis()
    worker_available = bool(client and _has_active_worker(client))
    if mode == 'auto' and (client is None or not worker_available):
        logger.warning(
            'Durable report worker unavailable; using explicit auto-mode '
            'thread fallback for session %s',
            session_id,
        )
        return _enqueue_thread(
            background_report_task,
            session_id,
            defer_start=defer_thread_start,
        )
    if client is None:
        raise ReportQueueUnavailable('Redis 不可用，报告任务未入队')

    try:
        from rq import Retry
        from rq.exceptions import DuplicateJobError
        from rq.job import Job

        intervals = _retry_intervals()
        retry = (
            Retry(max=len(intervals), interval=intervals)
            if intervals
            else None
        )
        job_id = f'interview-report-{session_id}-{submission_count}'
        queue = _queue(client)
        try:
            job = queue.enqueue_call(
                func=background_report_task,
                args=(session_id,),
                timeout=Config.REPORT_JOB_TIMEOUT_SECONDS,
                result_ttl=Config.REPORT_JOB_RESULT_TTL_SECONDS,
                failure_ttl=Config.REPORT_JOB_FAILURE_TTL_SECONDS,
                description=f'Generate interview report {session_id}',
                job_id=job_id,
                retry=retry,
                unique=True,
                meta={
                    'session_id': session_id,
                    'submission_count': submission_count,
                },
            )
        except DuplicateJobError:
            job = Job.fetch(job_id, connection=client)
        return {
            'job_id': job.id,
            'backend': 'rq',
            'worker_available': worker_available,
            'durable': True,
        }
    except ReportQueueError:
        raise
    except Exception as exc:
        raise ReportQueueError(f'RQ 入队失败: {exc}') from exc


def _status_value(status):
    return getattr(status, 'value', str(status))


def get_job_status(job_id):
    if not job_id:
        return 'unknown'
    client = _get_redis()
    if client is None:
        return 'unavailable'
    try:
        from rq.job import Job

        return _status_value(
            Job.fetch(job_id, connection=client).get_status(refresh=True)
        )
    except Exception:
        return 'missing'


def get_queue_health():
    """Return non-sensitive queue readiness and backlog metrics."""
    mode = _queue_mode()
    if mode == 'thread':
        return {
            'mode': mode,
            'status': 'local-only',
            'ready': True,
            'durable': False,
            'redis': 'not-required',
            'workers': 0,
            'queued': 0,
            'started': 0,
            'scheduled': 0,
            'failed': 0,
        }

    client = _get_redis(force=True)
    if client is None:
        ready = mode != 'rq'
        return {
            'mode': mode,
            'status': 'degraded' if ready else 'unavailable',
            'ready': ready,
            'durable': False,
            'redis': 'unavailable',
            'workers': 0,
            'queued': 0,
            'started': 0,
            'scheduled': 0,
            'failed': 0,
        }

    try:
        from rq.registry import (
            FailedJobRegistry,
            ScheduledJobRegistry,
            StartedJobRegistry,
        )

        queue = _queue(client)
        workers = _active_workers(client)
        counts = {
            'queued': queue.count,
            'started': StartedJobRegistry(
                queue=queue,
                connection=client,
            ).count,
            'scheduled': ScheduledJobRegistry(
                queue=queue,
                connection=client,
            ).count,
            'failed': FailedJobRegistry(
                queue=queue,
                connection=client,
            ).count,
        }
        durable_ready = bool(workers)
        return {
            'mode': mode,
            'status': 'ready' if durable_ready else 'no-worker',
            'ready': durable_ready if mode == 'rq' else True,
            'durable': durable_ready,
            'redis': 'ok',
            'workers': len(workers),
            **counts,
        }
    except Exception as exc:
        logger.exception('Unable to inspect report queue')
        return {
            'mode': mode,
            'status': 'error',
            'ready': mode != 'rq',
            'durable': False,
            'redis': 'ok',
            'workers': 0,
            'queued': 0,
            'started': 0,
            'scheduled': 0,
            'failed': 0,
            'error': str(exc)[:200],
        }


def sync_report_job_state(session, missing_after_minutes=15):
    """Synchronize one processing session with its durable RQ job."""
    if (
        session.status != 'processing'
        or session.report_queue_backend != 'rq'
    ):
        return False

    status = get_job_status(session.report_job_id)
    if status == 'unavailable':
        return False

    changed = session.report_queue_status != status
    session.report_queue_status = status
    terminal = {'failed', 'stopped', 'canceled'}
    stale_missing = (
        status == 'missing'
        and session.report_enqueued_at
        and session.report_enqueued_at
        < datetime.now() - timedelta(minutes=missing_after_minutes)
    )
    inconsistent_finished = status == 'finished'
    if status in terminal or stale_missing or inconsistent_finished:
        session.status = 'failed'
        session.report_queue_status = 'failed'
        session.report_finished_at = datetime.now()
        session.report_error = (
            f'报告队列任务状态异常（{status}），请重新提交生成。'
        )
        changed = True
    return changed


def reconcile_report_jobs(missing_after_minutes=15):
    """Mark terminal/missing durable jobs and refresh persisted queue status."""
    from .. import db
    from ..models import InterviewSession

    client = _get_redis(force=True)
    if client is None:
        return {'checked': 0, 'failed': 0, 'unavailable': True}

    sessions = InterviewSession.query.filter_by(
        status='processing',
        report_queue_backend='rq',
    ).all()
    failed = 0
    for session in sessions:
        was_processing = session.status == 'processing'
        sync_report_job_state(
            session,
            missing_after_minutes=missing_after_minutes,
        )
        if was_processing and session.status == 'failed':
            failed += 1
    if sessions:
        db.session.commit()
    return {
        'checked': len(sessions),
        'failed': failed,
        'unavailable': False,
    }


def queue_probe_task(value='ok'):
    """Small importable task used for worker deployment smoke tests."""
    return {
        'value': value,
        'worker_host': socket.gethostname(),
        'worker_pid': os.getpid(),
    }


def run_worker(burst=False):
    """Run the dedicated report worker with retry scheduling enabled."""
    client = _get_redis(force=True)
    if client is None:
        raise ReportQueueUnavailable('Redis 不可用，Worker 无法启动')

    from rq import Worker

    reconcile_report_jobs()

    worker_name = os.environ.get(
        'REPORT_WORKER_NAME',
        f'interview-report-{socket.gethostname()}-{os.getpid()}',
    )
    worker = Worker(
        [_queue(client)],
        connection=client,
        name=worker_name,
    )
    return worker.work(
        burst=burst,
        with_scheduler=True,
        logging_level=os.environ.get('REPORT_WORKER_LOG_LEVEL', 'INFO'),
    )


def register_queue_commands(app):
    import click

    @app.cli.command('queue-status')
    def queue_status_command():
        """Show queue readiness and backlog without exposing credentials."""
        health = get_queue_health()
        for key in (
            'mode',
            'status',
            'ready',
            'durable',
            'redis',
            'workers',
            'queued',
            'started',
            'scheduled',
            'failed',
        ):
            click.echo(f'{key}={health[key]}')
        if not health['ready']:
            raise click.ClickException('报告队列未就绪')

    @app.cli.command('reconcile-report-jobs')
    @click.option('--missing-after-minutes', default=15, type=int)
    def reconcile_report_jobs_command(missing_after_minutes):
        """Reconcile persisted processing sessions with durable RQ jobs."""
        result = reconcile_report_jobs(
            missing_after_minutes=max(1, missing_after_minutes),
        )
        click.echo(
            f"checked={result['checked']} failed={result['failed']} "
            f"unavailable={'yes' if result['unavailable'] else 'no'}"
        )
        if result['unavailable']:
            raise click.ClickException('Redis 不可用，未执行状态校准')

    @app.cli.command('queue-probe')
    @click.option('--timeout', default=10, type=int)
    def queue_probe_command(timeout):
        """Enqueue a real job and wait briefly for a dedicated worker."""
        client = _get_redis(force=True)
        if client is None:
            raise click.ClickException('Redis 不可用')
        if not _has_active_worker(client):
            raise click.ClickException('没有活跃的报告 Worker')

        job = _queue(client).enqueue_call(
            func=queue_probe_task,
            args=('probe-ok',),
            timeout=30,
            result_ttl=60,
            failure_ttl=60,
            job_id=f'interview-queue-probe-{uuid.uuid4().hex}',
        )
        deadline = monotonic() + max(1, min(timeout, 60))
        while monotonic() < deadline:
            job.refresh()
            status = _status_value(job.get_status())
            if status == 'finished':
                click.echo(
                    f'job={job.id} status=finished '
                    f'worker_pid={job.result["worker_pid"]}'
                )
                return
            if status in {'failed', 'stopped', 'canceled'}:
                raise click.ClickException(
                    f'探针任务失败，状态为 {status}'
                )
            time.sleep(0.2)
        raise click.ClickException('等待 Worker 执行探针任务超时')
