"""在临时项目安装技能，观测自然请求是否真正读取或调用技能。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from eval_support import SKILL, clean_env, read_json, write_json

NAME = 'industrial-explainer-storyboard'


def detect_trigger(stream: str) -> tuple[bool, bool]:
    """只信真实 tool_use 事件；文本声称使用、展示目录和普通字符串不算触发。"""
    triggered, completed = False, False
    for line in stream.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get('type') == 'result':
            completed = not event.get('is_error', False) and event.get('subtype', 'success') == 'success'
        if event.get('type') != 'assistant':
            continue
        for item in event.get('message', {}).get('content', []):
            if not isinstance(item, dict) or item.get('type') != 'tool_use':
                continue
            tool, args = item.get('name'), item.get('input', {})
            if tool == 'Skill' and args.get('skill', '').split(':')[-1] == NAME:
                triggered = True
            if tool == 'Read':
                path = Path(args.get('file_path', ''))
                if path.name == 'SKILL.md' and path.parent.name == NAME:
                    triggered = True
            if tool == 'Bash':
                # 只认可直接读取指定入口的命令，grep/ls/echo 不视为加载。
                import shlex
                try:
                    words = shlex.split(args.get('command', ''))
                except ValueError:
                    continue
                if words and words[0] in {'cat', 'head', 'tail', 'sed'} and any(
                    Path(w).name == 'SKILL.md' and Path(w).parent.name == NAME for w in words[1:]
                ):
                    triggered = True
    return triggered, completed


def run_one(case: dict, folder: Path, timeout: int, runner: Any = None) -> dict:
    runner = runner or subprocess.run
    folder.mkdir(parents=True, exist_ok=False)
    status: dict = {'returncode': None, 'error': None}
    with tempfile.TemporaryDirectory(prefix='storyboard-trigger-') as temporary:
        sandbox = Path(temporary)
        target = sandbox / '.claude/skills' / NAME
        target.mkdir(parents=True)
        shutil.copy2(SKILL / 'SKILL.md', target / 'SKILL.md')
        for name in ('scripts', 'references'):
            shutil.copytree(SKILL / name, target / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        fixture = SKILL / 'evals/fixtures/standard'
        for name in ('facts.json', 'project.json', 'assets.json', 'rig.json', 'shotlist.json'):
            shutil.copy2(fixture / name, sandbox / name)
        # 不提及技能名称或加载要求，不附加工作流提示。
        prompt = case['prompt']
        command = ['claude', '-p', '--model', 'claude-opus-5-5', '--output-format', 'stream-json', '--verbose',
                   '--setting-sources', 'project', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                   '--no-session-persistence', '--tools', 'Skill,Read,Write,Edit,Bash',
                   '--allowedTools', 'Skill,Read,Write,Edit,Bash', '--permission-mode', 'acceptEdits']
        (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
        write_json(folder / 'command.json', command)
        try:
            completed = runner(command, input=prompt, cwd=sandbox, env=clean_env(), capture_output=True,
                               text=True, timeout=timeout)
            status['returncode'] = completed.returncode
            (folder / 'stdout.jsonl').write_text(completed.stdout or '', encoding='utf-8')
            (folder / 'stderr.txt').write_text(completed.stderr or '', encoding='utf-8')
        except (OSError, subprocess.TimeoutExpired) as exc:
            status['error'] = f'触发评测调用失败：{exc}'
        write_json(folder / 'run-status.json', status)
    return score_one(case, folder)


def score_one(case: dict, folder: Path) -> dict:
    result = {'name': case['name'], 'expected': case['expected'], 'status': '失败', 'triggered': None}
    try:
        status = read_json(folder / 'run-status.json')
        if status.get('error') or status.get('returncode') != 0:
            raise ValueError(status.get('error') or '模型进程退出失败')
        triggered, completed = detect_trigger((folder / 'stdout.jsonl').read_text(encoding='utf-8'))
        if not completed:
            raise ValueError('缺少成功结束事件，不能记为未触发或通过')
        result.update(status='已评分', triggered=triggered, passed=triggered == case['expected'])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result['error'] = f'触发评测未完成：{exc}'
    write_json(folder / 'grading.json', result)
    return result


def aggregate(results: list[dict]) -> dict:
    summary: dict = {'results': results, 'expected_runs': len(results),
                     'completed': sum(r['status'] == '已评分' for r in results)}
    for expected, key in ((True, 'trigger_rate'), (False, 'false_trigger_rate')):
        chosen = [r for r in results if r['expected'] == expected and r['status'] == '已评分']
        summary[key] = sum(r['triggered'] for r in chosen) / len(chosen) if chosen else None
        summary[key + '_n'] = len(chosen)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='自然提问触发评测：每条默认两次，不提示加载技能。')
    parser.add_argument('--only', help='仅运行指定提问名称')
    parser.add_argument('--runs', type=int, default=2, help='每条运行次数，默认 2')
    parser.add_argument('--timeout', type=int, default=900, help='每次模型调用超时秒数')
    parser.add_argument('--iteration', type=int, help='指定新触发评测轮次')
    parser.add_argument('--score-only', type=Path, help='只解析既有触发日志，不调用模型')
    args = parser.parse_args(argv)
    cases = read_json(SKILL / 'evals/trigger_evals.json')['evals']
    cases = [c for c in cases if args.only is None or c['name'] == args.only]
    if not cases or args.runs < 1 or args.timeout < 1:
        parser.error('场景名不存在，或运行次数/超时无效')
    if args.score_only:
        output = args.score_only.resolve()
        if not output.is_dir():
            parser.error('评分目录不存在')
        manifest = read_json(output / 'run-manifest.json')
    else:
        workspace = SKILL / 'evals/workspace'
        existing = [int(p.name.split('-')[-1]) for p in workspace.glob('trigger-iteration-*') if p.name.split('-')[-1].isdigit()]
        iteration = args.iteration if args.iteration is not None else max(existing, default=0) + 1
        if iteration < 1:
            parser.error('轮次必须为正数')
        output = workspace / f'trigger-iteration-{iteration}'
        try:
            output.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            parser.error('轮次已存在，拒绝覆盖')
        manifest = {'cases': {c['name']: args.runs for c in cases}}
        write_json(output / 'run-manifest.json', manifest)
    results = []
    for case in cases:
        for run in range(1, manifest['cases'].get(case['name'], 0) + 1):
            print(f"正在检查触发：{case['name']} / 第 {run} 次", flush=True)
            folder = output / case['name'] / f'run-{run}'
            results.append(score_one(case, folder) if args.score_only else run_one(case, folder, args.timeout))
    if args.score_only and args.only:
        for case in read_json(SKILL / 'evals/trigger_evals.json')['evals']:
            if case['name'] == args.only:
                continue
            for run in range(1, manifest['cases'].get(case['name'], 0) + 1):
                saved = output / case['name'] / f'run-{run}' / 'grading.json'
                results.append(read_json(saved) if saved.exists() else {'name': case['name'], 'expected': case['expected'], 'status': '失败', 'triggered': None})
    summary = aggregate(results)
    write_json(output / 'trigger-benchmark.json', summary)
    def rate(key: str) -> str:
        return '未完成' if summary[key] is None else f'{summary[key]:.1%}（n={summary[key + "_n"]}）'
    report = f'完成 {summary["completed"]}/{summary["expected_runs"]} 次；触发率 {rate("trigger_rate")}；误触发率 {rate("false_trigger_rate")}。失败不计入有效分母。\n'
    (output / 'trigger-benchmark.md').write_text(report, encoding='utf-8')
    print(report)
    return 0 if results and all(r['status'] == '已评分' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
