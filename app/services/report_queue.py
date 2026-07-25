"""
面试报告生成任务队列。

策略：Redis 可用时用 RQ（独立 worker 进程，进程隔离、不随 Flask 重启而丢）；
Redis 不可用时回退到 daemon Thread，保证本地无 Redis 也能跑。

任务函数：app.api.interview.background_report_task(session_id)
"""
import os
from threading import Thread

REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')
QUEUE_NAME = 'interview_reports'

_redis_client = None
_redis_checked = False


def _get_redis():
    """返回可用的 redis 客户端，或 None（已缓存检查结果）。"""
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    try:
        import redis
        client = redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception as e:
        print(f"[queue] Redis 不可用，将回退到 Thread: {e}")
        _redis_client = None
        return None


def is_rq_available():
    """仅当 Redis 可用且目标队列有活跃 worker 时返回 True。"""
    client = _get_redis()
    return client is not None and _has_active_worker(client)


def _has_active_worker(client):
    """避免 Redis 存活但无人消费时把报告永久留在队列中。"""
    try:
        from rq import Queue, Worker
        queue = Queue(QUEUE_NAME, connection=client)
        return Worker.count(connection=client, queue=queue) > 0
    except Exception as e:
        print(f"[queue] 无法确认 RQ worker 状态，将回退到 Thread: {e}")
        return False


def reset_check():
    """重置探测缓存（用于 worker 或重新探测）。"""
    global _redis_client, _redis_checked
    _redis_client = None
    _redis_checked = False


def enqueue_report(session_id):
    """
    入队报告生成任务。
    返回 (job_id | None, backend)：
      - RQ 成功：({'job_id': 'xxx', 'backend': 'rq'})
      - 回退 Thread：({'job_id': None, 'backend': 'thread'})
    失败保证：任一路径都返回 dict，调用方不崩。
    """
    # 延迟导入，避免循环依赖
    try:
        from ..api.interview import background_report_task
    except Exception as e:
        print(f"[queue] 无法导入任务函数，回退 Thread: {e}")
        return {'job_id': None, 'backend': 'none', 'error': str(e)}

    client = _get_redis()
    if client is not None and _has_active_worker(client):
        try:
            from rq import Queue
            q = Queue(QUEUE_NAME, connection=client)
            job = q.enqueue(
                background_report_task,
                args=(session_id,),
                job_timeout='10m',
                result_ttl='24h',
                failure_ttl='24h',
            )
            return {'job_id': job.id, 'backend': 'rq'}
        except Exception as e:
            print(f"[queue] RQ 入队失败，回退 Thread: {e}")
    elif client is not None:
        print("[queue] Redis 可用但 interview_reports 无活跃 worker，将回退到 Thread")

    # 回退：daemon 线程（进程重启会丢，但本地无 Redis 时可用）
    t = Thread(target=_thread_runner, args=(background_report_task, session_id), daemon=True)
    t.start()
    return {'job_id': None, 'backend': 'thread'}


def _thread_runner(fn, session_id):
    """Thread 回退包装：吞掉异常只打印，避免线程静默崩溃。"""
    try:
        fn(session_id)
    except Exception as e:
        print(f"[queue][thread] 任务异常: {e}")


def get_job_status(job_id):
    """查询 RQ 任务状态（thread 回退时返回 unknown）。"""
    if not job_id:
        return 'unknown'
    client = _get_redis()
    if client is None:
        return 'unknown'
    try:
        from rq.job import Job
        job = Job.fetch(job_id, connection=client)
        return job.get_status()  # queued/started/finished/failed
    except Exception:
        return 'unknown'
