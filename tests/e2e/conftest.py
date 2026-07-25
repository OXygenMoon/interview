"""Live-server and Chromium fixtures for isolated E2E tests."""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = PROJECT_ROOT / 'test-results'


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _wait_until_healthy(url, process, log_path):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f'{url}/healthz', timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    log = log_path.read_text(encoding='utf-8', errors='replace')
    raise RuntimeError(f'E2E server did not become healthy.\n{log}')


@pytest.fixture(scope='session')
def live_server(tmp_path_factory):
    runtime_dir = tmp_path_factory.mktemp('interview-e2e')
    database_path = runtime_dir / 'e2e.db'
    server_log = runtime_dir / 'server.log'
    port = _free_port()
    base_url = f'http://127.0.0.1:{port}'

    env = os.environ.copy()
    env.update({
        'APP_ENV': 'testing',
        'APP_HOST': '127.0.0.1',
        'APP_PORT': str(port),
        'DATABASE_URL': f'sqlite:///{database_path}',
        'SECRET_KEY': 'e2e-only-secret-key',
        'LLM_API_KEY': 'e2e-placeholder-key',
        'REPORT_QUEUE_MODE': 'thread',
        'CSRF_ENABLED': 'true',
        'SESSION_COOKIE_SECURE': 'false',
        'FLASK_DEBUG': '0',
        'USE_RELOADER': 'False',
        'PYTHONUNBUFFERED': '1',
    })

    bootstrap = subprocess.run(
        [sys.executable, '-m', 'flask', '--app', 'run.py', 'bootstrap-db'],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if bootstrap.returncode:
        raise RuntimeError(
            f'Could not bootstrap E2E database.\n'
            f'{bootstrap.stdout}\n{bootstrap.stderr}'
        )
    subprocess.run(
        [sys.executable, '-m', 'tests.e2e.seed_database'],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    with server_log.open('w', encoding='utf-8') as log_file:
        process = subprocess.Popen(
            [sys.executable, 'run.py'],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_until_healthy(base_url, process, server_log)
            yield base_url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture(scope='session')
def browser_instance():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(request, browser_instance, live_server):
    ARTIFACT_ROOT.mkdir(exist_ok=True)
    context = browser_instance.new_context(
        locale='zh-CN',
        viewport={'width': 1440, 'height': 1000},
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    browser_page = context.new_page()

    def handle_external(route):
        request_url = route.request.url
        if request_url.startswith(live_server):
            route.continue_()
        elif 'marked' in request_url:
            route.fulfill(
                status=200,
                content_type='application/javascript',
                body='window.marked={parse:(value)=>value};',
            )
        elif 'chart' in request_url:
            route.fulfill(
                status=200,
                content_type='application/javascript',
                body=(
                    'class Chart { constructor() {} };'
                    'Chart.defaults={font:{},color:""};window.Chart=Chart;'
                ),
            )
        elif route.request.resource_type == 'stylesheet':
            route.fulfill(status=200, content_type='text/css', body='')
        else:
            route.fulfill(status=204, body='')

    browser_page.route('https://**/*', handle_external)
    yield browser_page

    failed = getattr(request.node, 'rep_call', None)
    failed = bool(failed and failed.failed)
    artifact_name = request.node.nodeid.replace('/', '-').replace('::', '-')
    if failed:
        browser_page.screenshot(
            path=ARTIFACT_ROOT / f'{artifact_name}.png',
            full_page=True,
        )
        context.tracing.stop(path=ARTIFACT_ROOT / f'{artifact_name}.zip')
    else:
        context.tracing.stop()
    context.close()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f'rep_{report.when}', report)
