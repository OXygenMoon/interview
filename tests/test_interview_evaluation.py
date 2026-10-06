"""Checks for the replay evaluator; these are not live scoring results."""

import json
from pathlib import Path

from scripts.evaluate_interview_rounds import (
    compare_profiles,
    error_info,
    history_for,
    judge_case,
)


def test_round_fixtures_use_identical_questions_across_profiles():
    path = Path(__file__).resolve().parents[1] / 'docs/interview-simulation-cases-v3.json'
    fixtures = json.loads(path.read_text())
    for round_num in (1, 2, 3):
        cases = [case for case in fixtures['cases'] if case['round_num'] == round_num]
        assert {case['profile'] for case in cases} == {'weak', 'competent', 'strong'}
        assert len({tuple(pair['question'] for pair in case['qa_pairs']) for case in cases}) == 1
        for case in cases:
            history = history_for(case)
            assert len(history) == 12
            assert [message.id for message in history] == list(range(1, 13))
            assert all(message.sender == 'user' for message in history[1::2])


def test_blocked_or_missing_profiles_do_not_count_as_ordering_pass():
    assert all(row['ordering_passed'] is None for row in compare_profiles([]))
    rows = [{
        'round_num': 1, 'profile': profile, 'status': 'blocked', 'report': None,
    } for profile in ('weak', 'competent', 'strong')]
    assert compare_profiles(rows)[0]['ordering_passed'] is None


def test_equal_or_reversed_scores_fail_within_round_comparison():
    def rows(scores):
        return [{
            'round_num': 2, 'profile': profile, 'status': 'evaluated',
            'report': {'overall': {'total_score': score}},
        } for profile, score in zip(('weak', 'competent', 'strong'), scores)]

    assert compare_profiles(rows((15, 60, 85)))[1]['ordering_passed'] is True
    assert compare_profiles(rows((60, 60, 60)))[1]['ordering_passed'] is False
    assert compare_profiles(rows((85, 60, 15)))[1]['ordering_passed'] is False


def test_high_total_with_every_answer_unacceptable_is_flagged():
    case = {'diagnostic_score_range': [70, 100], 'qa_pairs': [1, 2, 3]}
    report = {
        'overall': {'total_score': 90},
        'details_list': [{'is_good': False} for _ in range(3)],
    }
    checks = {check['check']: check['passed'] for check in judge_case(case, report)}
    assert checks['provisional_score_range'] is True
    assert checks['high_total_has_some_acceptable_answers'] is False


def test_failure_record_excludes_arbitrary_exception_text_and_private_fields():
    private_marker = 'private-account-information'
    root = RuntimeError(private_marker)
    root.status_code = 402
    root.body = {'code': 30001, 'message': private_marker, 'api_key': private_marker}
    wrapped = RuntimeError('service error')
    wrapped.__cause__ = root
    record = error_info(wrapped)
    assert record['http_status'] == 402
    assert record['provider_code'] == 30001
    assert private_marker not in json.dumps(record)
