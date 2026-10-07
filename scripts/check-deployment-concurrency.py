"""Opt-in live deployment probe using temporary users, cleaned up on exit.

Run on the deployment host with its virtualenv and Nix library environment.
--chat makes real billable model/TTS requests; --speech uses the bundled sample.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
from pathlib import Path
import secrets
import statistics
import sys
import threading
import time

import requests
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TokenParser(HTMLParser):
    token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name') == 'csrf_token':
            self.token = attrs.get('value')
        if tag == 'meta' and attrs.get('name') == 'csrf-token':
            self.token = attrs.get('content')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:20018')
    parser.add_argument('--users', type=int, default=32)
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument('--speech', action='store_true')
    parser.add_argument('--chat', action='store_true')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not 1 <= args.users <= 64 or not 1 <= args.rounds <= 100:
        parser.error('users must be 1..64 and rounds must be 1..100')

    from production_wsgi import app
    from app import db
    from app.models import ChatMessage, InterviewSession, User

    base = args.base_url.rstrip('/')
    prefix = f'deployprobe_{secrets.token_hex(5)}_'
    password = secrets.token_urlsafe(24)
    clients = [requests.Session() for _ in range(args.users)]
    user_ids = []
    interview_ids = []
    audio_paths = set()
    report = {'users': args.users, 'base_url': base, 'phases': {}}

    def phase(name, operation, rounds=1):
        barrier = threading.Barrier(args.users)

        def run(index):
            barrier.wait(timeout=30)
            rows = []
            for _ in range(rounds):
                started = time.monotonic()
                try:
                    details = operation(index)
                    ok = details.pop('ok')
                except Exception as exc:
                    ok = False
                    details = {'error': f'{type(exc).__name__}: {str(exc)[:240]}'}
                rows.append({'ok': ok, 'seconds': time.monotonic() - started, **details})
            return rows

        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=args.users) as executor:
            rows = [row for group in executor.map(run, range(args.users)) for row in group]
        durations = sorted(row['seconds'] for row in rows)
        summary = {
            'requests': len(rows),
            'success': sum(row['ok'] for row in rows),
            'wall_seconds': round(time.monotonic() - started, 3),
            'median_seconds': round(statistics.median(durations), 3),
            'p95_seconds': round(durations[int(0.95 * (len(durations) - 1))], 3),
            'max_seconds': round(max(durations), 3),
            'failures': [row for row in rows if not row['ok']],
        }
        if name == 'chat':
            summary['responses_with_audio'] = sum(row.get('audio_count', 0) > 0 for row in rows)
            summary['max_first_token_seconds'] = max((row.get('first_token_seconds', 0) for row in rows), default=0)
        report['phases'][name] = summary
        print(name, json.dumps(summary, ensure_ascii=False), flush=True)

    def login(index):
        client = clients[index]
        response = client.get(base + '/login', timeout=30)
        response.raise_for_status()
        token = TokenParser()
        token.feed(response.text)
        if not token.token:
            raise RuntimeError('login page did not provide CSRF token')
        client.headers['X-CSRF-Token'] = token.token
        response = client.post(base + '/login', data={
            'username': prefix + str(index), 'password': password,
            'csrf_token': token.token,
        }, allow_redirects=False, timeout=60)
        return {'ok': response.status_code == 302 and '/login' not in response.headers.get('Location', ''), 'http': response.status_code}

    def page(index):
        response = clients[index].get(base + '/', allow_redirects=False, timeout=60)
        return {'ok': response.status_code == 200, 'http': response.status_code}

    def speech(index):
        sample = ROOT / '.local/asr/sensevoice/test_wavs/zh.wav'
        with sample.open('rb') as audio:
            response = clients[index].post(base + '/api/interview/transcribe',
                files={'audio': ('probe.wav', audio, 'audio/wav')}, timeout=180)
        payload = response.json()
        return {'ok': response.status_code == 200 and payload.get('status') == 'success' and bool(payload.get('text')), 'http': response.status_code, 'status': payload.get('status')}

    def chat(index):
        started = time.monotonic()
        first_token = None
        done = False
        errors = []
        audio_count = 0
        with clients[index].post(base + f'/api/interview/{interview_ids[index]}/chat',
            json={'message': '我熟悉 Python 的列表和字典。请只问一个简短的问题，控制在二十个字以内。'},
            stream=True, timeout=(10, 180)) as response:
            for line in response.iter_lines(chunk_size=1):
                if not line.startswith(b'data: '):
                    continue
                event = json.loads(line[6:])
                if event.get('type') == 'token' and first_token is None:
                    first_token = round(time.monotonic() - started, 3)
                if event.get('type') == 'error':
                    errors.append(event.get('message', 'stream error'))
                if event.get('type') == 'done':
                    done = True
                if event.get('type') == 'audio':
                    audio_count += 1
                    filename = event.get('url', '').rsplit('/', 1)[-1]
                    path = ROOT / 'app/static/uploads/audio' / filename
                    if filename and path.is_file():
                        audio_paths.add(path)
            return {'ok': response.status_code == 200 and done and first_token is not None and not errors,
                    'http': response.status_code, 'errors': errors, 'audio_count': audio_count,
                    'first_token_seconds': first_token or 0}

    try:
        with app.app_context():
            hashed = generate_password_hash(password)
            for index in range(args.users):
                user = User(username=prefix + str(index), password_hash=hashed,
                            truename='Deployment probe', role='student', active=True)
                db.session.add(user)
                db.session.flush()
                user_ids.append(user.id)
                if args.chat:
                    interview = InterviewSession(user_id=user.id, target_role='Python工程师',
                                                 difficulty='标准模式', status='ongoing')
                    db.session.add(interview)
                    db.session.flush()
                    interview_ids.append(interview.id)
            db.session.commit()
        phase('login', login)
        if report['phases']['login']['success'] != args.users:
            raise RuntimeError('Login probe failed; skipping authenticated probes')
        phase('pages', page, rounds=args.rounds)
        if args.speech:
            # Warm all workers through HTTP before measuring the simultaneous batch.
            phase('speech_first_use', speech)
            phase('speech_warm', speech)
        if args.chat:
            phase('chat', chat)
    finally:
        for client in clients:
            client.close()
        with app.app_context():
            db.session.rollback()
            if interview_ids:
                ChatMessage.query.filter(ChatMessage.session_id.in_(interview_ids)).delete(synchronize_session=False)
                InterviewSession.query.filter(InterviewSession.id.in_(interview_ids)).delete(synchronize_session=False)
            if user_ids:
                User.query.filter(User.id.in_(user_ids), User.username.startswith(prefix)).delete(synchronize_session=False)
            db.session.commit()
            report['cleanup'] = {'remaining_probe_users': User.query.filter(User.username.startswith(prefix)).count()}
        for path in audio_paths:
            path.unlink(missing_ok=True)
        report['passed'] = bool(report['phases']) and all(
            phase['success'] == phase['requests'] for phase in report['phases'].values()
        )
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print('cleanup', report['cleanup'], flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
