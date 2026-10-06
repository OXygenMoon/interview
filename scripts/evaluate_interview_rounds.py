"""Replay three interview rounds through the real, database-free report service.

Run from the project root:
  .venv/bin/python scripts/evaluate_interview_rounds.py
  .venv/bin/python scripts/evaluate_interview_rounds.py --prepare-only

Uses the configured model without replacing it or accepting error fallbacks.
Synthetic answers are fixed; a completed replay is not a live AI conversation.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def history_for(case):
    history = []
    for pair in case['qa_pairs']:
        history.extend([
            SimpleNamespace(
                id=len(history) + 1, sender='ai', content=pair['question'],
                generation_status='completed', visual_context=None,
            ),
            SimpleNamespace(
                id=len(history) + 2, sender='user', content=pair['answer'],
                generation_status='completed', visual_context=None,
            ),
        ])
    if not history:
        history.append(SimpleNamespace(
            id=1, sender='ai', content='请介绍你与岗位相关的经历。',
            generation_status='completed', visual_context=None,
        ))
    return history


def error_info(exc):
    # Service errors preserve the SDK exception as their cause. Do not include
    # arbitrary exception text, API keys, HTTP headers or account information.
    cause = exc
    while cause.__cause__ is not None:
        cause = cause.__cause__
    body = getattr(cause, 'body', None)
    code = body.get('code') if isinstance(body, dict) else None
    status = getattr(cause, 'status_code', None)
    result = {'error_type': type(cause).__name__, 'http_status': status, 'provider_code': code}
    if status == 402:
        result['reason'] = 'configured provider has insufficient account balance'
    return result


def judge_case(case, report):
    score = report['overall']['total_score']
    checks = []
    if 'expected_total' in case:
        checks.append({'check': 'edge_total', 'passed': score == case['expected_total']})
    else:
        low, high = case['diagnostic_score_range']
        checks.append({'check': 'provisional_score_range', 'passed': low <= score <= high})
        details = report['details_list']
        checks.append({'check': 'review_count', 'passed': len(details) == len(case['qa_pairs'])})
        if score >= 75:
            checks.append({
                'check': 'high_total_has_some_acceptable_answers',
                'passed': any(review['is_good'] for review in details),
            })
    return checks


def compare_profiles(rows):
    comparisons = []
    for round_num in (1, 2, 3):
        profiles = {
            row['profile']: row['report']['overall']['total_score']
            for row in rows
            if row['round_num'] == round_num and row.get('profile')
            and row['status'] == 'evaluated'
        }
        ready = all(profile in profiles for profile in ('weak', 'competent', 'strong'))
        comparisons.append({
            'round_num': round_num,
            'scores': profiles,
            'ordering_passed': (
                profiles['weak'] < profiles['competent'] < profiles['strong']
                if ready else None
            ),
        })
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true', help='Validate fixtures without model calls.')
    parser.add_argument('--repeats', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/interview-simulation-results-v3.json')
    args = parser.parse_args()
    fixtures_path = ROOT / 'docs/interview-simulation-cases-v3.json'
    fixtures = json.loads(fixtures_path.read_text())
    for round_num in (1, 2, 3):
        same_round = [case for case in fixtures['cases'] if case['round_num'] == round_num]
        assert len(same_round) == 3
        assert len({tuple(pair['question'] for pair in case['qa_pairs']) for case in same_round}) == 1
        assert all(len(case['qa_pairs']) == 6 for case in same_round)
    if args.prepare_only:
        print('Prepared: 3 rounds × 3 profiles × 6 questions; 4 edge cases. No model calls.')
        return 0

    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from app.services import ai_agent as ai
    ai.client = ai.client.with_options(timeout=45, max_retries=0)
    suite = {
        'evaluated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'sample_type': fixtures['sample_type'],
        'fixtures_sha256': hashlib.sha256(fixtures_path.read_bytes()).hexdigest(),
        'prompt_sha256': hashlib.sha256((ROOT / 'app/services/interview_prompts.py').read_bytes()).hexdigest(),
        'report_prompt_version': ai.REPORT_PROMPT_VERSION,
        'report_model': ai.Config.LLM_REPORT,
        'repeats': args.repeats,
        'limitations': [
            'Fixed synthetic replay, not live AI-generated questions.',
            'Score ranges are diagnostic hypotheses, not calibrated ground truth.',
            'Rule-based zero is an evidence placeholder, not a measured ability score.',
            'Only compare profiles within the same round; do not compare rounds directly.',
        ],
        'cases': [],
        'comparisons': [],
    }
    # This real service branch needs no inference and is useful even if billing
    # blocks every model request. Its result must not count as model validation.
    empty = fixtures['edge_cases'][0]
    empty_report = ai.generate_interview_report(history_for(empty), fixtures['role'])
    suite['cases'].append({
        'case_id': empty['case_id'], 'round_num': empty['round_num'],
        'status': 'rule_only', 'model_inference': False,
        'report': empty_report, 'checks': judge_case(empty, empty_report),
    })

    cases = fixtures['cases'] + fixtures['edge_cases'][1:]
    try:
        # Probe once before paid report calls. SDK errors cannot be mistaken for
        # the non-streaming interview function's polite fallback response.
        ai.client.chat.completions.create(
            model=ai.Config.LLM_REPORT,
            messages=[{'role': 'user', 'content': '只回复 OK。'}],
            max_tokens=8, temperature=0,
        )
    except Exception as exc:
        suite['suite_status'] = 'blocked'
        suite['provider_probe'] = {'status': 'blocked', **error_info(exc)}
        for case in cases:
            suite['cases'].append({
                'case_id': case['case_id'], 'round_num': case['round_num'],
                'profile': case.get('profile'), 'status': 'blocked',
                'model_inference': False, 'report': None, 'checks': None,
            })
        suite['comparisons'] = compare_profiles(suite['cases'])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n')
        print('Blocked:', suite['provider_probe'], flush=True)
        print('Saved:', args.output, flush=True)
        return 2

    for repetition in range(1, args.repeats + 1):
        round_rows = []
        for case in cases:
            row = {
                'case_id': case['case_id'], 'round_num': case['round_num'],
                'profile': case.get('profile'), 'repetition': repetition,
            }
            try:
                report = ai.generate_interview_report(
                    history_for(case), fixtures['role'], round_num=case['round_num'],
                    difficulty=case.get('difficulty', '标准模式'),
                    position_context=fixtures['position_context'],
                )
                row.update(status='evaluated', model_inference=True,
                           report=report, checks=judge_case(case, report))
                print(case['case_id'], report['overall']['total_score'], row['checks'], flush=True)
            except Exception as exc:
                row.update(status='failed', report=None, checks=None, error=error_info(exc))
                print(case['case_id'], row['error'], flush=True)
            round_rows.append(row)
            suite['cases'].append(row)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n')
        suite['comparisons'].append({'repetition': repetition, 'rounds': compare_profiles(round_rows)})
    evaluated = [row for row in suite['cases'] if row['status'] == 'evaluated']
    checks_passed = all(check['passed'] for row in evaluated for check in row['checks'])
    ordered = all(
        comparison['ordering_passed'] is True
        for run in suite['comparisons'] for comparison in run['rounds']
    )
    suite['suite_status'] = (
        'passed' if len(evaluated) == len(cases) * args.repeats and checks_passed and ordered
        else 'needs_review'
    )
    args.output.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n')
    print('Suite:', suite['suite_status'], 'Saved:', args.output, flush=True)
    return 0 if suite['suite_status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
