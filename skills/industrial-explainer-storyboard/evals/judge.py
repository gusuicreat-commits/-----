"""随机 A/B 文采盲评；离线重评分仅解析缓存，不调用模型。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import subprocess
import tempfile
from typing import Any

from eval_support import (SKILL, GROUPS, METRICS, clean_env, fingerprint, read_json,
                          resolved, run_folder, run_ids, select_cases, summarize, write_json)


def parse_scores(stdout: str) -> dict:
    envelope = json.loads(stdout)
    if envelope.get('is_error'):
        raise ValueError('盲评模型返回错误')
    value = envelope.get('structured_output', envelope.get('result', envelope))
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError('盲评结果必须为 JSON 对象')
    for label in ('A', 'B'):
        if not isinstance(value.get(label), dict) or set(value[label]) != set(METRICS):
            raise ValueError('盲评缺少六项评分')
        if any(type(v) is not int or not 1 <= v <= 5 for v in value[label].values()):
            raise ValueError('盲评分数须为 1–5 的整数')
    difference = sum(value['A'].values()) - sum(value['B'].values())
    winner = 'A' if difference > 0 else 'B' if difference < 0 else 'tie'
    if value.get('winner') != winner or not isinstance(value.get('reason'), str) or not value['reason'].strip():
        raise ValueError('盲评胜者与等权总分不一致，或缺少中文理由')
    return value


def judge_pair(output: Path, case: dict, run: int, *, score_only: bool = False,
               timeout: int = 900, runner: Any = None, rng: Any = None) -> dict:
    runner = runner or subprocess.run
    root = output / case['name']
    root.mkdir(parents=True, exist_ok=True)
    prefix = root / f'judge-{run}'
    result: dict = {'status': '未完成', 'case': case['name'], 'run': run}
    try:
        candidates = {g: resolved(case, run_folder(output, case['name'], g, run))['shots'] for g in GROUPS}
        digest = fingerprint({'case': case['prompt'], 'candidates': candidates})
        mapping_path = prefix.with_suffix('.mapping.json')
        stdout_path = prefix.with_suffix('.stdout.json')
        status_path = prefix.with_suffix('.status.json')
        if score_only:
            mapping = read_json(mapping_path)
            if mapping.get('fingerprint') != digest:
                raise ValueError('台词已变化，旧盲评不能复用；请重新运行 judge.py')
            status = read_json(status_path)
            if status.get('returncode') != 0 or status.get('error'):
                raise ValueError('原盲评调用失败，不能重评分为成功')
        else:
            groups = list(GROUPS)
            (rng or random.SystemRandom()).shuffle(groups)
            mapping = {'A': groups[0], 'B': groups[1], 'fingerprint': digest}
            write_json(mapping_path, mapping)
            rubric = (SKILL / 'evals/judge_prompt.md').read_text(encoding='utf-8')
            payload = {'需求': case['prompt']}
            for label in ('A', 'B'):
                payload[label] = [{'时长秒': s['duration_s'], '台词': s['narration_resolved']} for s in candidates[mapping[label]]]
            prompt = rubric + '\n待评数据：\n' + json.dumps(payload, ensure_ascii=False)
            prefix.with_suffix('.prompt.txt').write_text(prompt, encoding='utf-8')
            command = ['claude', '-p', '--model', 'claude-opus-5-5', '--output-format', 'json',
                       '--setting-sources', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                       '--no-session-persistence', '--disable-slash-commands', '--tools', '']
            write_json(prefix.with_suffix('.command.json'), command)
            status = {'returncode': None, 'error': '调用尚未完成'}
            write_json(status_path, status)
            with tempfile.TemporaryDirectory(prefix='storyboard-judge-') as temporary:
                try:
                    completed = runner(command, input=prompt, cwd=Path(temporary), env=clean_env(),
                                       text=True, capture_output=True, timeout=timeout)
                    stdout_path.write_text(completed.stdout or '', encoding='utf-8')
                    prefix.with_suffix('.stderr.txt').write_text(completed.stderr or '', encoding='utf-8')
                    status = {'returncode': completed.returncode, 'error': None}
                except (OSError, subprocess.TimeoutExpired) as exc:
                    status['error'] = f'盲评调用失败：{exc}'
                write_json(status_path, status)
            if status['returncode'] != 0:
                raise ValueError(status['error'] or '盲评进程退出失败，详见 stderr 日志')
        if set(mapping.get(k) for k in ('A', 'B')) != set(GROUPS):
            raise ValueError('盲评标签映射无效')
        scores = parse_scores(stdout_path.read_text(encoding='utf-8'))
        result.update(status='已评分', groups={mapping[k]: scores[k] for k in ('A', 'B')},
                      winner_group=mapping[scores['winner']] if scores['winner'] != 'tie' else 'tie',
                      reason=scores['reason'], fingerprint=digest)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result['error'] = f'文采盲评未完成：{exc}'
    write_json(prefix.with_suffix('.json'), result)
    return result


def evaluate(output: Path, cases: list[dict], *, score_only: bool = False,
             timeout: int = 900, runner: Any = None) -> bool:
    results = []
    for case in cases:
        for run in run_ids(output, case['name']):
            print(f"正在评阅文采：{case['name']} / 第 {run} 次", flush=True)
            results.append(judge_pair(output, case, run, score_only=score_only, timeout=timeout, runner=runner))
    summarize(output)
    return bool(results) and all(r['status'] == '已评分' for r in results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='随机 A/B 文采盲评；真实性仍由校验脚本负责。')
    parser.add_argument('--iteration', type=Path, help='已有 iteration-N 目录')
    parser.add_argument('--only', help='仅处理指定场景')
    parser.add_argument('--score-only', type=Path, help='只解析此轮缓存，不调用模型')
    parser.add_argument('--timeout', type=int, default=900, help='单次模型调用超时秒数')
    args = parser.parse_args(argv)
    output = args.score_only or args.iteration
    try:
        cases = select_cases(args.only)
        if output is None or not output.is_dir() or args.timeout < 1:
            raise ValueError('请指定有效轮次目录和正数超时')
    except ValueError as exc:
        parser.error(str(exc))
    ok = evaluate(output.resolve(), cases, score_only=bool(args.score_only), timeout=args.timeout)
    from report import generate
    generate(output.resolve())
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
