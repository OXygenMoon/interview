"""Replay both student modes across all three rounds, without a business database.

Uses configured providers and fixed synthetic answers; also records one real
interviewer follow-up per mode/round for manual difficulty review.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_interview_rounds import compare_profiles, error_info, history_for, judge_case


def validate_fixtures(fixtures):
    for difficulty in ('新手模式', '标准模式'):
        for round_num in (1, 2, 3):
            cases = [c for c in fixtures['cases']
                     if c['difficulty'] == difficulty and c['round_num'] == round_num]
            assert len(cases) == 3
            assert {c['profile'] for c in cases} == {'weak', 'competent', 'strong'}
            assert len({tuple(p['question'] for p in c['qa_pairs']) for c in cases}) == 1
            assert all(len(c['qa_pairs']) == 4 for c in cases)
    assert len(fixtures['cases']) == 18 and len(fixtures['edge_cases']) == 6


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/student-interview-results-v4.json')
    args = parser.parse_args()
    fixture_path = ROOT / 'docs/student-interview-cases-v4.json'
    fixtures = json.loads(fixture_path.read_text())
    validate_fixtures(fixtures)
    if args.prepare_only:
        print('Prepared: 2 modes × 3 rounds × 3 profiles × 4 questions; 6 edge cases.')
        return 0

    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from app.services import ai_agent as ai
    ai.client = ai.client.with_options(timeout=45, max_retries=0)
    suite = {
        'evaluated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'sample_type': fixtures['sample_type'],
        'fixtures_sha256': hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        'prompt_sha256': hashlib.sha256((ROOT / 'app/services/interview_prompts.py').read_bytes()).hexdigest(),
        'chat_prompt_version': ai.CHAT_PROMPT_VERSION,
        'report_prompt_version': ai.REPORT_PROMPT_VERSION,
        'chat_model': ai.Config.LLM_MODEL_NAME,
        'report_model': ai.Config.LLM_REPORT,
        'limitations': ['Synthetic answers, not actual student interviews.',
                        'Diagnostic score ranges are hypotheses, not human-labelled ground truth.',
                        'Generated follow-ups require manual difficulty review.',
                        'No business database reads or writes.'],
        'cases': [], 'comparisons': [], 'interviewer_followups': [],
    }

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n')

    def evaluate(case):
        row = {key: case[key] for key in ('case_id', 'difficulty', 'round_num')}
        row['profile'] = case.get('profile')
        try:
            report = ai.generate_interview_report(
                history_for(case), fixtures['role'], round_num=case['round_num'],
                difficulty=case['difficulty'], position_context=fixtures['position_context'],
            )
            row.update(status='evaluated' if report.get('evaluation_source') != 'rule' else 'rule_only',
                       model_inference=report.get('evaluation_source') != 'rule',
                       report=report, checks=judge_case(case, report))
            if case.get('profile') and report['overall']['total_score'] >= 75:
                row['checks'].append({
                    'check': 'high_score_has_majority_acceptable_answers',
                    'passed': sum(d['is_good'] for d in report['details_list']) >= 3,
                })
        except Exception as exc:
            row.update(status='failed', report=None, checks=None, error=error_info(exc))
        return row

    # Probe before launching paid reports; do not treat polite chat fallbacks as success.
    try:
        ai.client.chat.completions.create(
            **ai.chat_request_options(), model=ai.Config.LLM_REPORT,
            messages=[{'role': 'user', 'content': '只回复OK。'}], max_tokens=16, temperature=0,
        )
    except Exception as exc:
        suite.update(suite_status='blocked', provider_probe=error_info(exc))
        suite['cases'] = [evaluate(c) for c in fixtures['edge_cases'] if not c['qa_pairs']]
        save()
        print('Blocked:', suite['provider_probe'])
        return 2

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(evaluate, c) for c in fixtures['cases'] + fixtures['edge_cases']]
        for future in as_completed(futures):
            row = future.result()
            suite['cases'].append(row)
            save()
            print(row['case_id'], row['status'],
                  row['report']['overall']['total_score'] if row['report'] else row['error'], flush=True)

    for difficulty in ('新手模式', '标准模式'):
        suite['comparisons'].append({
            'difficulty': difficulty,
            'rounds': compare_profiles([r for r in suite['cases'] if r['difficulty'] == difficulty]),
        })
        for round_num in (1, 2, 3):
            case = next(c for c in fixtures['cases'] if c['difficulty'] == difficulty
                        and c['round_num'] == round_num and c['profile'] == 'competent')
            # Ask the real interviewer to continue after two basic student answers.
            history = history_for({**case, 'qa_pairs': case['qa_pairs'][:2]})
            row = {'difficulty': difficulty, 'round_num': round_num,
                   'history': [{'sender': m.sender, 'content': m.content} for m in history]}
            try:
                response = ai.client.chat.completions.create(
                    **ai.chat_request_options(), model=ai.Config.LLM_MODEL_NAME,
                    messages=ai._build_interview_messages(
                        history, fixtures['role'], difficulty, '', '', round_num,
                    ), temperature=0.7, max_tokens=512,
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise ValueError('empty interviewer follow-up')
                row.update(status='generated', question=content)
            except Exception as exc:
                row.update(status='failed', error=error_info(exc))
            suite['interviewer_followups'].append(row)
            save()
            print('Follow-up:', difficulty, round_num, row.get('question', row.get('error')), flush=True)

    passed = all(r['checks'] and all(c['passed'] for c in r['checks']) for r in suite['cases'])
    ordered = all(r['ordering_passed'] is True for group in suite['comparisons'] for r in group['rounds'])
    generated = all(r['status'] == 'generated' for r in suite['interviewer_followups'])
    suite['suite_status'] = 'passed' if passed and ordered and generated else 'needs_review'
    save()
    print('Suite:', suite['suite_status'], 'Saved:', args.output, flush=True)
    return 0 if suite['suite_status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
