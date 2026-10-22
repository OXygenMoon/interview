"""Resume polishing provider compatibility and failure handling."""

import os
from unittest.mock import Mock

import pytest
import requests
from flask import Flask

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app.api import resume
from app.config import Config


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        LOGIN_DISABLED=True,
        LLM_API_KEY='resume-test-key',
        LLM_BASE_URL='https://api.deepseek.com/v1/',
        LLM_MODEL_NAME='deepseek-flash',
        LLM_THINKING='disabled',
    )
    app.register_blueprint(resume.resume_bp, url_prefix='/api/resume')
    return app.test_client()


@pytest.fixture
def provider(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {
        'choices': [{'message': {'content': '负责数据核验，协同完成课程报告。'}, 'finish_reason': 'stop'}],
    }
    post = Mock(return_value=response)
    monkeypatch.setattr(resume.requests, 'post', post)
    return post


def optimize(client):
    return client.post('/api/resume/optimize', json={
        'content': '整理数据、检查表格，和同学合作完成课程报告。', 'type': '项目描述',
    })


def test_polishing_uses_current_app_deepseek_configuration(client, provider, monkeypatch):
    # A legacy module-level provider must not override the active app settings.
    monkeypatch.setattr(Config, 'LLM_BASE_URL', 'https://legacy.example/v1')
    monkeypatch.setattr(Config, 'LLM_THINKING', 'enabled')
    response = optimize(client)
    assert response.status_code == 200
    assert response.json == {'success': True, 'suggestion': '负责数据核验，协同完成课程报告。'}
    assert provider.call_args.args == ('https://api.deepseek.com/v1/chat/completions',)
    assert provider.call_args.kwargs['json']['model'] == 'deepseek-flash'
    assert provider.call_args.kwargs['json']['thinking'] == {'type': 'disabled'}


def test_other_providers_do_not_receive_deepseek_parameters(client, provider):
    client.application.config['LLM_BASE_URL'] = 'https://other.example/v1'
    assert optimize(client).json['success'] is True
    assert 'thinking' not in provider.call_args.kwargs['json']


def test_fenced_text_preserves_suggestion(client, provider):
    provider.return_value.json.return_value['choices'][0]['message']['content'] = (
        '```text\n负责数据核验，协同完成课程报告。\n```'
    )
    assert optimize(client).json['suggestion'] == '负责数据核验，协同完成课程报告。'


@pytest.mark.parametrize('payload', [
    {}, {'choices': []}, {'choices': [None]}, {'choices': [{'message': None}]},
    {'choices': [{'message': {'content': None}}]},
    {'choices': [{'message': {'content': '  '}}]},
    {'choices': [{'message': {'content': '半段文本'}, 'finish_reason': 'length'}]},
])
def test_unusable_output_does_not_become_suggestion(client, provider, payload):
    provider.return_value.json.return_value = payload
    response = optimize(client)
    assert response.status_code == 502
    assert response.json['success'] is False
    assert 'suggestion' not in response.json


@pytest.mark.parametrize('error,status', [
    (requests.exceptions.Timeout(), 504),
    (requests.exceptions.ConnectionError(), 502),
    (ValueError('invalid JSON'), 502),
])
def test_provider_errors_are_actionable(client, provider, error, status):
    if isinstance(error, ValueError):
        provider.return_value.json.side_effect = error
    else:
        provider.side_effect = error
    response = optimize(client)
    assert response.status_code == status
    assert response.json['success'] is False


def test_provider_rejection_is_not_reported_as_success(client, provider):
    provider.return_value.status_code = 401
    response = optimize(client)
    assert response.status_code == 502
    assert '401' in response.json['error']


@pytest.mark.parametrize('setting', ['LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL_NAME'])
def test_missing_configuration_does_not_call_provider(client, provider, setting):
    client.application.config[setting] = ''
    response = optimize(client)
    assert response.status_code == 500
    assert response.json['success'] is False
    provider.assert_not_called()


@pytest.mark.parametrize('payload', [[], ['invalid'], {'content': '  '}, {'content': 42}])
def test_invalid_input_does_not_call_provider(client, provider, payload):
    assert client.post('/api/resume/optimize', json=payload).status_code == 400
    provider.assert_not_called()
