"""Historical replays must use their own scoring code without changing the app."""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app.services import interview_prompts as current_prompts
from scripts.replay_interview_versions import VERSIONS, load_version, summary_for


@pytest.mark.parametrize('version', VERSIONS)
def test_historical_prompt_isolation_and_aggregation(version):
    current_version = current_prompts.REPORT_PROMPT_VERSION
    agent, metadata = load_version(version)
    assert metadata['report_prompt_version'].startswith(f'interview-report-{version}')
    if version != 'v3':
        assert agent.get_assessment_prompt.__module__.endswith(f'_replay_{version}_interview_prompts')
    if version in ('v6', 'v7', 'v8'):
        assert agent.dimension_answers.__module__.endswith(f'_replay_{version}_interview_coverage')
    assert current_prompts.REPORT_PROMPT_VERSION == current_version

    # v3 preserves a conservative model total; subsequent student versions
    # recompute weights. Replacing all aggregation with current code is wrong.
    payload = {'scores': dict.fromkeys(agent.REQUIRED_SCORE_DIMENSIONS, 80),
               'evaluated_dimensions': list(agent.REQUIRED_SCORE_DIMENSIONS),
               'total_score': 10, 'comment': '模拟评分测试。'}
    response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(payload)),
    )])
    with patch.object(agent.client.chat.completions, 'create', return_value=response):
        report = agent._get_overall_score('[]', '文员', 6, difficulty='新手模式')
    assert report['total_score'] == (10 if version == 'v3' else 80)
    agent.client.close()


def test_failed_replay_is_not_counted_as_a_low_score():
    summary = summary_for({'runs': [{'status': 'failed', 'report': None}]})
    assert summary == {'successful_runs': 0}
