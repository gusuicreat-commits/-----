"""评测共用的离线读取、分组统计与隔离调用工具。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
from typing import Any

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
from resolve_text import resolve_shots
from skill_io import read_json, write_json

GROUPS = ('with_skill', 'without_skill')
LABELS = {'with_skill': '使用技能', 'without_skill': '未使用技能'}
METRICS = ('hook', 'clarity', 'rhythm', 'appeal', 'tone', 'substance')
METRIC_LABELS = ('开场钩子', '外行可懂度', '节奏', '宣传感', '语气匹配', '内容实在')


def select_cases(only: str | None = None) -> list[dict]:
    cases = read_json(SKILL / 'evals/evals.json')['evals']
    chosen = [c for c in cases if only is None or c['name'] == only]
    if not chosen:
        raise ValueError(f'未知场景：{only}')
    return chosen


def run_ids(output: Path, case: str) -> list[int]:
    ids = {int(p.name[4:]) for group in GROUPS for p in (output / case / group).glob('run-*') if p.name[4:].isdigit()}
    if not ids and any((output / case / g / 'shotlist.json').exists() for g in GROUPS):
        return [1]
    return sorted(ids)


def run_folder(output: Path, case: str, group: str, run: int) -> Path:
    parent = output / case / group
    folder = parent / f'run-{run}'
    return parent if run == 1 and not folder.exists() and (parent / 'shotlist.json').exists() else folder


def resolved(case: dict, folder: Path) -> dict:
    facts = read_json(SKILL / 'evals/fixtures' / case['name'] / 'facts.json')
    shotlist = read_json(folder / 'shotlist.json')
    result = resolve_shots(facts, shotlist)
    if any(s['unresolved'] for s in result['shots']):
        raise ValueError('仍有未展开引用，不能交盲评')
    return result


def fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop('CLAUDECODE', None)
    return env


def stats(values: list[float]) -> dict:
    return {'n': len(values), 'mean': statistics.mean(values) if values else None,
            'std': statistics.stdev(values) if len(values) > 1 else 0.0 if values else None}


def formatted(value: dict, percent: bool = False) -> str:
    if not value['n']:
        return '未完成'
    scale = 100 if percent else 1
    suffix = '%' if percent else ''
    return f"{value['mean'] * scale:.2f} ± {value['std'] * scale:.2f}{suffix}（n={value['n']}）"


def summarize(output: Path) -> dict:
    """只统计已评分值，同时公开预期次数及失败数，缺失不能变成零分通过。"""
    rows = []
    manifest = read_json(output / 'run-manifest.json') if (output / 'run-manifest.json').exists() else {}
    for case in select_cases():
        ids = run_ids(output, case['name'])
        expected = manifest.get('cases', {}).get(case['name'], len(ids))
        if not expected and not ids:
            continue
        ids = sorted(set(ids) | set(range(1, expected + 1)))
        for group in GROUPS:
            grades, prose, wins = [], [], []
            for run in ids:
                folder = run_folder(output, case['name'], group, run)
                if (folder / 'grading.json').exists():
                    grades.append(read_json(folder / 'grading.json'))
                judge_file = output / case['name'] / f'judge-{run}.json'
                if judge_file.exists():
                    judged = read_json(judge_file)
                    if judged.get('status') == '已评分':
                        score = judged['groups'][group]
                        prose.append(statistics.mean(score.values()))
                        wins.append(1.0 if judged['winner_group'] == group else 0.0)
            valid = [g for g in grades if g['status'] == '已评分']
            rows.append({'case': case['name'], 'group': group, 'expected': expected,
                         'completed': len(valid), 'failed': max(0, expected - len(valid)),
                         'block': stats([g['block'] for g in valid]), 'warn': stats([g['warn'] for g in valid]),
                         'assertion_rate': stats([g['assertion_rate'] if g['status'] == '已评分' else 0.0 for g in grades]
                                                 + [0.0] * max(0, expected - len(grades))),
                         'traceability_rate': stats([g['traceability_rate'] for g in valid if g.get('traceability_rate') is not None]),
                         'prose': stats(prose), 'win_rate': stats(wins)})
    overall = {}
    for group in GROUPS:
        selected = [r for r in rows if r['group'] == group]
        overall[group] = {'expected': sum(r['expected'] for r in selected),
                          'completed': sum(r['completed'] for r in selected),
                          'judged': sum(r['prose']['n'] for r in selected)}
        for field in ('prose', 'win_rate'):
            count = sum(r[field]['n'] for r in selected)
            overall[group][field] = sum((r[field]['mean'] or 0) * r[field]['n'] for r in selected) / count if count else None
    result = {'rows': rows, 'overall': overall, 'note': '标准差采用样本标准差；文采仅统计成功盲评，胜率为获胜次数/有效配对数，平局不计胜。真实性由独立校验器判断。'}
    write_json(output / 'benchmark.json', result)
    lines = ['# 分镜技能对照评测', '', result['note'], '',
             '| 场景 | 组别 | 完成/预期 | block 均值±标准差 | warn 均值±标准差 | 断言通过率 | 可溯源率 | 文采均分 | 胜率 |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append('| ' + ' | '.join([row['case'], LABELS[row['group']], f"{row['completed']}/{row['expected']}",
                     formatted(row['block']), formatted(row['warn']), formatted(row['assertion_rate'], True),
                     formatted(row['traceability_rate'], True), formatted(row['prose']), formatted(row['win_rate'], True)]) + ' |')
    (output / 'benchmark.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result
