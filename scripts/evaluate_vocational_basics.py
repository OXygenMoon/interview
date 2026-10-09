"""Replay the user's basic-answer calibration in all modes without a database.

Calls the configured report provider. Results distinguish actual model output
from errors; the correct-answer case should score 80–90, with all answers accepted.
"""

import contextlib
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_interview_rounds import error_info, history_for, judge_case


def calibration_checks(case, report):
    checks = judge_case(case, report)
    checks.append({
        'check': 'basic_answer_acceptance',
        'passed': [row['is_good'] for row in report['details_list']] == case['expected_is_good'],
    })
    if case['case_id'] == 'correct_general_basics':
        scores = report['overall']['scores']
        checks.append({
            'check': 'assessed_basics_not_scored_low',
            'passed': all(scores[d] >= 80 for d in ('专业技能', '逻辑思维', '抗压能力')),
        })
    return checks


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from app.services import ai_agent as ai
    ai.client = ai.client.with_options(timeout=45, max_retries=0)
    fixture_path = ROOT / 'docs/vocational-basic-cases-v8.json'
    fixtures = json.loads(fixture_path.read_text())
    result = {
        'evaluated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'sample_type': fixtures['sample_type'],
        'fixtures_sha256': hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        'prompt_sha256': hashlib.sha256((ROOT / 'app/services/interview_prompts.py').read_bytes()).hexdigest(),
        'chat_prompt_version': ai.CHAT_PROMPT_VERSION,
        'report_prompt_version': ai.REPORT_PROMPT_VERSION,
        'report_model': ai.Config.LLM_REPORT,
        'limitations': ['Reconstructed answers, not an original student transcript.',
                        'Single replay per case and mode; scores may vary on subsequent calls.',
                        'No business database reads or writes.'],
        'cases': [],
    }
    output = ROOT / 'docs/vocational-basic-results-v8.json'
    for difficulty in ai.STUDENT_MODES:
        for case in fixtures['cases']:
            row = {'case_id': case['case_id'], 'difficulty': difficulty, 'round_num': 1}
            try:
                # Avoid emitting arbitrary provider exception bodies or private data.
                with contextlib.redirect_stdout(io.StringIO()):
                    report = ai.generate_interview_report(
                        history_for(case), fixtures['role'], round_num=1,
                        difficulty=difficulty, position_context=fixtures['position_context'],
                    )
                row.update(status='evaluated', report=report, checks=calibration_checks(case, report))
                print(difficulty, case['case_id'], report['overall']['total_score'],
                      'PASS' if all(c['passed'] for c in row['checks']) else 'FAIL', flush=True)
            except Exception as exc:
                row.update(status='failed', report=None, checks=[], error=error_info(exc))
                print(difficulty, case['case_id'], row['error'], flush=True)
            result['cases'].append(row)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return 0 if all(r['status'] == 'evaluated' and all(c['passed'] for c in r['checks'])
                    for r in result['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
