"""Replay an existing interview with exact historical v3–v8 scoring services.

Historical modules run in isolated processes; only their import namespaces are
renamed. All models/provider settings remain fixed. No business database is used.
"""

import argparse
import ast
from concurrent.futures import ProcessPoolExecutor, as_completed
import contextlib
from datetime import datetime
import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import statistics
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VERSIONS = {
    'v3': '6978968', 'v4': '4c2a07d', 'v5': '2e40a01',
    'v6': 'c943a96', 'v7': '42aaee3', 'v8': '706b9bb',
}
DIMENSIONS = ('专业技能', '逻辑思维', '语言表达', '抗压能力', '礼仪态度')


def git_source(ref, path):
    return subprocess.check_output(['git', 'show', f'{ref}:{path}'], cwd=ROOT, text=True)


def load_version(version):
    """Load original code without replacing current application modules/files."""
    ref = VERSIONS[version]
    names = {name: f'_replay_{version}_{name}' for name in ('interview_prompts', 'interview_coverage')}

    class RenameHistoricalImports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level == 1 and node.module in names:
                node.module = names[node.module]
            return node

    def module_for(name, source):
        qualified = f'app.services._replay_{version}_{name}'
        module = ModuleType(qualified)
        module.__package__ = 'app.services'
        module.__file__ = f'git:{ref}:app/services/{name}.py'
        sys.modules[qualified] = module
        tree = RenameHistoricalImports().visit(ast.parse(source))
        exec(compile(tree, module.__file__, 'exec'), module.__dict__)
        return module

    prompts = git_source(ref, 'app/services/interview_prompts.py')
    prompt_module = module_for('interview_prompts', prompts)
    assert prompt_module.REPORT_PROMPT_VERSION.startswith(f'interview-report-{version}')
    if version in ('v6', 'v7', 'v8'):
        module_for('interview_coverage', git_source(ref, 'app/services/interview_coverage.py'))
    source = git_source(ref, 'app/services/ai_agent.py')
    agent = module_for('ai_agent', source)
    metadata = {
        'version': version,
        'commit': subprocess.check_output(['git', 'rev-parse', ref], cwd=ROOT, text=True).strip(),
        'commit_date': subprocess.check_output(['git', 'show', '-s', '--format=%aI', ref], cwd=ROOT, text=True).strip(),
        'chat_prompt_version': agent.CHAT_PROMPT_VERSION,
        'report_prompt_version': agent.REPORT_PROMPT_VERSION,
        'prompt_sha256': hashlib.sha256(prompts.encode()).hexdigest(),
        'scoring_service_sha256': hashlib.sha256(source.encode()).hexdigest(),
    }
    return agent, metadata


def evaluate_version(version, input_path, repeats):
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from scripts.evaluate_interview_rounds import error_info
    fixture = json.loads(Path(input_path).read_text())
    with contextlib.redirect_stdout(io.StringIO()):
        agent, metadata = load_version(version)
    sdk = agent.client.with_options(timeout=60, max_retries=1)
    result = {**metadata, 'model': agent.Config.LLM_REPORT, 'runs': []}
    history = [SimpleNamespace(**row) for row in fixture['history']]
    for repetition in range(1, repeats + 1):
        calls = []

        def create(**kwargs):
            response = sdk.chat.completions.create(**kwargs)
            calls.append({
                'model': kwargs['model'], 'temperature': kwargs.get('temperature'),
                'provider_model': response.model,
                'response_id': response.id,
                'raw_response': response.choices[0].message.content,
            })
            return response

        agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        row = {'repetition': repetition}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                report = agent.generate_interview_report(
                    history, fixture['target_role'], round_num=fixture['round_num'],
                    difficulty=fixture['difficulty'], position_context=fixture['position_context'],
                )
            row.update(status='evaluated', report=report, model_calls=calls)
        except Exception as exc:
            row.update(status='failed', report=None, error=error_info(exc), model_calls=calls)
        result['runs'].append(row)
    return result


def summary_for(row):
    good = [r['report'] for r in row['runs'] if r['status'] == 'evaluated']
    if not good:
        return {'successful_runs': 0}
    totals = [r['overall']['total_score'] for r in good]
    representative = sorted(good, key=lambda r: r['overall']['total_score'])[len(good) // 2]
    return {
        'successful_runs': len(good), 'totals': totals,
        'median_total': statistics.median(totals), 'total_range': [min(totals), max(totals)],
        'median_dimensions': {d: statistics.median(r['overall']['scores'][d] for r in good) for d in DIMENSIONS},
        'representative_report': representative,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / '.local/evaluations/interview225/input.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/interview-225-v3-v8-results.json')
    parser.add_argument('--repeats', type=int, default=3, choices=range(1, 6))
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    source = json.loads(args.input.read_text())
    suite = {
        'evaluated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'session_id': source['session_id'], 'role': source['target_role'],
        'difficulty': source['difficulty'], 'round_num': source['round_num'],
        'input_sha256': hashlib.sha256(args.input.read_bytes()).hexdigest(),
        'input_source': 'Exact original completed transcript and position snapshot read from server session 225.',
        'repeats_per_version': args.repeats,
        'original_v3_total': source['original_v3_report']['total_score'],
        'original_v3_dimensions': source['original_v3_report']['radar_data'],
        'limitations': [
            'Replays the scoring stage with a fixed existing transcript; no new questions or finish-time gating.',
            'Uses each historical prompt AND its historical aggregation logic, with the same current report model.',
            'This is a new model call, not an exact reproduction of a past model response.',
            'Dimension medians are calculated separately and may not sum to the median total.',
            'No business records or production processes are changed.',
        ],
        'versions': [],
    }
    if args.prepare_only:
        for version in VERSIONS:
            _, metadata = load_version(version)
            print(metadata['version'], metadata['report_prompt_version'], metadata['commit'][:7])
        return 0
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn')) as executor:
        tasks = {executor.submit(evaluate_version, version, str(args.input), args.repeats): version for version in VERSIONS}
        for task in as_completed(tasks):
            row = task.result()
            row['summary'] = summary_for(row)
            suite['versions'].append(row)
            suite['versions'].sort(key=lambda r: r['version'])
            args.output.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + '\n')
            print(row['version'], row['summary'].get('totals', []),
                  f"{row['summary']['successful_runs']}/{args.repeats}", flush=True)
    return 0 if all(row['summary']['successful_runs'] == args.repeats for row in suite['versions']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
