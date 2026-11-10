"""真实模型 A/B 运行器；离线测试只调用评分函数或替换进程入口。"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
from compute_analogy import compute
from resolve_text import PLACEHOLDER
from skill_io import read_json, write_json


def fact_references(shotlist: dict) -> set[str]:
    references = {a['fact'] for a in shotlist.get('analogies', [])}
    for shot in shotlist['shots']:
        references.update(shot.get('fact_refs', []))
        references.update(p for p in PLACEHOLDER.findall(shot.get('narration', '')) if p.startswith('F_'))
        references.update(shot.get('params', {}).get('facts', []))
        if shot.get('params', {}).get('fact'):
            references.add(shot['params']['fact'])
    return references


def assertion_passes(assertion: dict, shotlist: dict, report: dict, facts: dict,
                     assets: dict, delivery: str) -> bool:
    kind = assertion['type']
    shots, issues = shotlist['shots'], report['issues']
    if kind == 'no_blocks':
        return not any(i['severity'] == 'block' or i['code'] == 'CHECK_ERROR' for i in issues)
    if kind == 'schema':
        return not report.get('input_errors')
    if kind == 'shot_count':
        return assertion['min'] <= len(shots) <= assertion['max']
    if kind == 'duration':
        return assertion['min'] <= sum(s['duration_s'] for s in shots) <= assertion['max']
    if kind == 'confirmed_only':
        by_id = {f['id']: f for f in facts['facts']}
        return all(fid in by_id and by_id[fid]['status'] in {'verified', 'confirmed'} for fid in fact_references(shotlist))
    if kind == 'computed_analogies':
        by_id = {f['id']: f for f in facts['facts']}
        for analogy in shotlist.get('analogies', []):
            expected = compute(analogy['id'], by_id[analogy['fact']], analogy['ref'], analogy['axis'])
            if any(analogy.get(k) != expected[k] for k in ('ratio', 'text')):
                return False
        return True
    if kind == 'reference_claim':
        reference_ids = {a['id'] for a in assets['assets'] if a.get('provenance') == 'reference'}
        return all(not any(w in s['narration'] for w in ('这台', '本机', '我们的')) for s in shots
                   if reference_ids.intersection(set(s.get('asset_refs', [])) | {s.get('params', {}).get('asset')}))
    if kind == 'required_kinds':
        return set(assertion['kinds']) <= {s['kind'] for s in shots}
    if kind == 'no_kind':
        return all(s['kind'] != assertion['kind'] for s in shots)
    if kind == 'no_fact':
        return assertion['fact'] not in fact_references(shotlist)
    if kind == 'human_review':
        return assertion['fact'] in delivery and any(word in delivery for word in ('待确认', '人工确认', '未确认', '待核实'))
    if kind == 'no_code_prefix':
        return not any(i['code'].startswith(assertion['prefix']) for i in issues)
    raise ValueError(f"未知断言类型：{kind}")


def grade(case: dict, folder: Path, runner: Any = None) -> dict:
    """始终用原始夹具打分；不采信模型修改后的输入或自报通过。"""
    fixture = SKILL / 'evals' / 'fixtures' / case['name']
    runner = runner or subprocess.run
    summary: dict[str, Any] = {'status': '失败', 'block': None, 'warn': None, 'assertions': []}
    try:
        command = [sys.executable, str(SKILL / 'scripts/validate_shotlist.py'),
                   '--facts', str(fixture / 'facts.json'), '--shotlist', str(folder / 'shotlist.json'),
                   '--assets', str(fixture / 'assets.json'), '--project', str(fixture / 'project.json'),
                   '--rig', str(fixture / 'rig.json'), '--out', str(folder / 'validation-report.json')]
        completed = runner(command, capture_output=True, text=True, timeout=60)
        (folder / 'validation.stdout.txt').write_text(completed.stdout or '', encoding='utf-8')
        (folder / 'validation.stderr.txt').write_text(completed.stderr or '', encoding='utf-8')
        if completed.returncode not in (0, 1):
            raise ValueError(f'校验进程退出码 {completed.returncode}，详见 validation.stderr.txt')
        report, shotlist = read_json(folder / 'validation-report.json'), read_json(folder / 'shotlist.json')
        summary.update(block=report['counts']['block'], warn=report['counts']['warn'], status='已评分')
        delivery = (folder / 'delivery-report.md').read_text(encoding='utf-8') if (folder / 'delivery-report.md').exists() else ''
        facts, assets = read_json(fixture / 'facts.json'), read_json(fixture / 'assets.json')
        for assertion in case['assertions']:
            try:
                passed = assertion_passes(assertion, shotlist, report, facts, assets, delivery)
                error = None
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                passed, error = False, f'断言输入无效：{exc}'
            summary['assertions'].append({'id': assertion['id'], 'passed': passed, 'error': error})
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        summary['error'] = str(exc)
        summary['assertions'] = [{'id': a['id'], 'passed': False} for a in case['assertions']]
    status_path = folder / 'run-status.json'
    if status_path.exists():
        status = read_json(status_path)
        if status.get('returncode') != 0 or status.get('error'):
            summary['status'] = '模型运行失败'
            summary['error'] = status.get('error') or f"模型退出码 {status.get('returncode')}"
            summary['assertions'] = [{**a, 'passed': False} for a in summary['assertions']]
    summary['assertion_rate'] = sum(a['passed'] for a in summary['assertions']) / len(case['assertions'])
    write_json(folder / 'grading.json', summary)
    return summary


def run_case(case: dict, group: str, destination: Path, timeout: int, runner: Any = None) -> dict:
    runner = runner or subprocess.run
    destination.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='industrial-storyboard-eval-') as temporary:
        sandbox = Path(temporary)
        # 临时目录不在仓库内，避免对照组读取仓库中的技能与正反例。
        for relative in case['files']:
            source = SKILL / 'evals' / relative
            shutil.copy2(source, sandbox / source.name)
        if group == 'with_skill':
            skill_copy = sandbox / '.claude/skills/industrial-explainer-storyboard'
            skill_copy.mkdir(parents=True)
            shutil.copy2(SKILL / 'SKILL.md', skill_copy / 'SKILL.md')
            for name in ('scripts', 'references'):
                shutil.copytree(SKILL / name, skill_copy / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        prompt = case['prompt'] + '''
请只使用当前工作目录提供的 facts.json、assets.json、project.json、rig.json、brief.md。
不要联网、修改输入参数或读取其他项目。交付 shotlist.json 和中文 delivery-report.md。
分镜格式：顶层 version=1、title、fps=30、width=1920、height=1080、shots、analogies。
每镜头字段：id、kind、source、duration_s、narration、fact_refs、analogy_refs、asset_refs、params、review:{status:"pending",note:""}。
kind 支持 title/model_orbit/analogy/motion/exploded/data_card/real_media/ai_broll/weld_macro/outro，source 支持 model/real/ai/graphic。
台词参数格式为 {{F_id}}，类比为 {{A_id}}；analogies 每项包含 id/fact/ref/axis/ratio/text。
报告说明问题、修法和人工确认项。最终文件必须写到当前目录，不能仅在回复里输出。
'''
        command = ['claude', '-p', '--model', 'claude-opus-5-5', '--setting-sources', 'project',
                   '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--no-session-persistence',
                   '--tools', 'Read,Write,Edit,Bash', '--allowedTools', 'Read,Write,Edit,Bash',
                   '--permission-mode', 'acceptEdits', '--output-format', 'json']
        if group == 'with_skill':
            prompt += '\n请加载当前项目 .claude/skills/industrial-explainer-storyboard/SKILL.md 并按其步骤工作。\n'
        else:
            command.append('--disable-slash-commands')
        (destination / 'prompt.txt').write_text(prompt, encoding='utf-8')
        write_json(destination / 'command.json', command)
        # 不改用户 HOME/配置；两组共用现有认证。仅移除嵌套会话标记。
        env = dict(os.environ)
        env.pop('CLAUDECODE', None)
        status = {'returncode': None, 'error': None}
        try:
            result = runner(command, input=prompt, cwd=sandbox, env=env,
                                    capture_output=True, text=True, timeout=timeout)
            status['returncode'] = result.returncode
            try:
                envelope = json.loads(result.stdout or '{}')
                if isinstance(envelope, dict) and envelope.get('is_error'):
                    status['error'] = '模型返回错误，详见 claude.stdout.json'
            except ValueError:
                status['error'] = '模型返回不是有效 JSON，详见 claude.stdout.json'
            (destination / 'claude.stdout.json').write_text(result.stdout or '', encoding='utf-8')
            (destination / 'claude.stderr.txt').write_text(result.stderr or '', encoding='utf-8')
        except (OSError, subprocess.TimeoutExpired) as exc:
            status['error'] = str(exc)
            for name, output in [('claude.stdout.json', getattr(exc, 'stdout', '')), ('claude.stderr.txt', getattr(exc, 'stderr', ''))]:
                text = output.decode('utf-8', errors='replace') if isinstance(output, bytes) else output or ''
                (destination / name).write_text(text, encoding='utf-8')
        write_json(destination / 'run-status.json', status)
        for path in sandbox.iterdir():
            if path.is_file() and path.suffix in {'.json', '.md', '.txt'}:
                # 模型自报报告保留，外部评分报告使用固定文件名。
                target = destination / ('model-' + path.name if path.name == 'validation-report.json' else path.name)
                shutil.copy2(path, target)
    return grade(case, destination, runner)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='真实模型双组评测；默认新建下一轮，不覆盖旧结果。')
    parser.add_argument('--iteration', type=int, help='指定正整数轮次，已存在时拒绝覆盖')
    parser.add_argument('--timeout', type=int, default=900, help='每次模型调用超时秒数')
    parser.add_argument('--score-only', type=Path, help='仅重新评分既有 iteration 目录，不调用模型')
    args = parser.parse_args(argv)
    cases = read_json(SKILL / 'evals/evals.json')['evals']
    if args.score_only:
        output = args.score_only.resolve()
        if not output.is_dir():
            parser.error('评分目录不存在')
    else:
        workspace = SKILL / 'evals/workspace'
        existing = [int(p.name.split('-')[-1]) for p in workspace.glob('iteration-*') if p.name.split('-')[-1].isdigit()]
        iteration = args.iteration if args.iteration is not None else max(existing, default=0) + 1
        if iteration < 1 or args.timeout <= 0:
            parser.error('轮次和超时必须为正数')
        output = workspace / f'iteration-{iteration}'
        output.mkdir(parents=True, exist_ok=False)
    rows = ['# 分镜技能对照评测', '', '真实模型结果以本轮日志为准；断言使用固定原始夹具评分，未执行或调用失败不得记为通过。', '',
            '| 场景 | 组别 | 状态 | block | warn | 断言通过率 |', '|---|---|---|---:|---:|---:|']
    results = []
    for case in cases:
        for group in ('with_skill', 'without_skill'):
            folder = output / case['name'] / group
            if args.score_only:
                folder.mkdir(parents=True, exist_ok=True)
                summary = grade(case, folder)
            else:
                print(f"正在评测 {case['name']} / {group}", flush=True)
                summary = run_case(case, group, folder, args.timeout)
            results.append({'case': case['name'], 'group': group, **deepcopy(summary)})
            rows.append(f"| {case['name']} | {group} | {summary['status']} | {summary['block'] if summary['block'] is not None else '未完成'} | {summary['warn'] if summary['warn'] is not None else '未完成'} | {summary['assertion_rate']:.0%} |")
            (output / 'benchmark.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    write_json(output / 'benchmark.json', results)
    print(f'评测已保存：{output / "benchmark.md"}')
    return 1 if any(r['status'] != '已评分' for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
