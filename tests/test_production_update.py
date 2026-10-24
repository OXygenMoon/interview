"""Deploy updates must install dependencies before importing the Flask app."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def deployment(tmp_path):
    shutil.copyfile(ROOT / 'run-production.sh', tmp_path / 'run-production.sh')
    (tmp_path / 'requirements.txt').write_text('lxml==6.1.1\n', encoding='utf-8')
    return tmp_path


def fake_python(deployment, directory):
    executable = deployment / directory / 'bin' / 'python'
    executable.parent.mkdir(parents=True)
    executable.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$UPDATE_TEST_LOG"
case "${UPDATE_FAIL_AT:-}" in
    install) if [ "${2:-} ${3:-}" = "pip install" ]; then exit 13; fi ;;
    check) if [ "${2:-} ${3:-}" = "pip check" ]; then exit 14; fi ;;
    migrate) if [ "${2:-}" = flask ]; then exit 15; fi ;;
esac
''', encoding='utf-8')
    executable.chmod(0o755)
    return executable


def run_update(deployment, fail_at=''):
    log = deployment / 'commands.log'
    env = dict(os.environ, UPDATE_TEST_LOG=str(log), UPDATE_FAIL_AT=fail_at)
    result = subprocess.run(['bash', str(deployment / 'run-production.sh'), 'update'],
                            cwd='/', env=env, capture_output=True, text=True, timeout=5)
    commands = log.read_text().splitlines() if log.exists() else []
    return result, commands


@pytest.mark.parametrize('directory', ['.venv', 'venv'])
def test_update_uses_project_python_for_install_check_and_migration(deployment, directory):
    python = fake_python(deployment, directory)
    result, commands = run_update(deployment)
    assert result.returncode == 0, result.stderr
    assert str(python) in result.stdout
    assert commands == [f'-m pip install -r {deployment}/requirements.txt',
                        '-m pip check', '-m flask --app run.py bootstrap-db']


@pytest.mark.parametrize('failure,exit_code,count', [('install', 13, 1), ('check', 14, 2), ('migrate', 15, 3)])
def test_update_stops_and_preserves_error_status(deployment, failure, exit_code, count):
    fake_python(deployment, 'venv')
    result, commands = run_update(deployment, failure)
    assert result.returncode == exit_code
    assert len(commands) == count
    if failure != 'migrate':
        assert not any('flask' in command for command in commands)


def test_update_requires_project_environment_instead_of_installing_globally(deployment):
    result, commands = run_update(deployment)
    assert result.returncode == 1
    assert 'python3 -m venv venv' in result.stderr
    assert commands == []
