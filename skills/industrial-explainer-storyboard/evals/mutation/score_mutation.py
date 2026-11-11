"""按预期问题码计召回，任何非信息级问题都计为正确样本误报。"""
from __future__ import annotations

from collections import Counter
import json
from copy import deepcopy
from pathlib import Path
import sys
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mutate import CATEGORIES, SKILL, build_baselines, mutations, positives
from skill_io import read_json, schema_errors
from validate_shotlist import validate


def score(validator: Callable[..., dict] = validate) -> dict:
    bases = build_baselines()
    bad = mutations(bases)
    good = bases + positives(bases)
    counts, hits = Counter(), Counter()
    signatures = {category: set() for category in CATEGORIES}
    def difference(before, after, path=''):
        if isinstance(before, dict) and isinstance(after, dict):
            return [leaf for key in sorted(before.keys() | after.keys())
                    for leaf in difference(before.get(key), after.get(key), path + '/' + key)]
        if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
            return [leaf for i, (a, b) in enumerate(zip(before, after)) for leaf in difference(a, b, path + '/' + str(i))]
        return [] if before == after else [(path, before, after)]
    by_name = {base['name']: base for base in bases}
    misses, false_positives = [], []
    schema = read_json(SKILL / 'scripts/shotlist.schema.json')
    for item in bad:
        # 只对实际故障差异去重；更换 baseline 名称、样本 ID 不产生新变体。
        signatures[item['category']].add(json.dumps(difference(
            {k: by_name[item['baseline']][k] for k in ('facts', 'shotlist', 'assets', 'rig')},
            {k: item[k] for k in ('facts', 'shotlist', 'assets', 'rig')}), ensure_ascii=False, sort_keys=True))
        report = validator(item['facts'], deepcopy(item['shotlist']), item['assets'], item['project'], item['rig'])
        codes = {i['code'] for i in report['issues'] if i['severity'] in {'block', 'warn'}}
        counts[item['category']] += 1
        if codes & set(item['expected']):
            hits[item['category']] += 1
        else:
            misses.append({'id': item['id'], 'expected': item['expected'], 'actual': sorted(codes)})
    for item in good:
        report = validator(item['facts'], deepcopy(item['shotlist']), item['assets'], item['project'], item['rig'])
        issues = [i for i in report['issues'] if i['severity'] != 'info' or i['code'] == 'CHECK_ERROR']
        errors = schema_errors(item['shotlist'], schema)
        if issues or errors:
            false_positives.append({'id': item.get('id', item['name']), 'issues': issues, 'schema': errors})
    rows = [{'category': c, 'label': label, 'total': counts[c], 'unique_faults': len(signatures[c]), 'caught': hits[c], 'recall': hits[c] / counts[c]}
            for c, (label, _) in CATEGORIES.items()]
    recall = sum(hits.values()) / len(bad)
    return {'rows': rows, 'total': len(bad), 'caught': sum(hits.values()), 'recall': recall,
            'correct_total': len(good), 'false_positive_rate': len(false_positives) / len(good),
            'misses': misses, 'false_positives': false_positives,
            'passed': recall >= .99 and all(r['recall'] >= .95 and r['unique_faults'] >= 10 for r in rows) and not false_positives}


def write_report(result: dict, path: Path) -> None:
    lines = ['# 准确度故障注入报告', '',
             '四套合格分镜取自 standard、bridge_crane、english_facts、reference_only 资料；行程与文字事实含明确标注的合成测试输入。',
             '每类12例，跨四套资料；按相对基线的实际故障差异去重，每类至少10种。命中必须包含该变异预期的问题码；无关警告不计召回。',
             '未确认事实、参考实拍冒认和绝对承诺沿用合同的 warn，召回统计 block/warn，不等于全部硬阻断。',
             '超速样本指运动已加速却伪标 speedup=1；合同允许有正确倍速标识的加速演示。', '',
             '| 错误类别 | 命中/样本 | 独立故障差异 | 召回率 |', '|---|---:|---:|---:|']
    for row in result['rows']:
        lines.append(f"| {row['label']} | {row['caught']}/{row['total']} | {row['unique_faults']} | {row['recall']:.1%} |")
    lines += ['', f"总召回：{result['caught']}/{result['total']}（{result['recall']:.1%}）。",
              f"误报：{len(result['false_positives'])}/{result['correct_total']}（{result['false_positive_rate']:.1%}）；合格基线4份 + 人工易误报样本20份。",
              f"门槛：每类≥95%，总计≥99%，误报=0。结果：{'通过' if result['passed'] else '未通过'}。", '',
              '运行：`python3 skills/industrial-explainer-storyboard/evals/mutation/score_mutation.py`。',
              '样本由 mutate.py 确定性生成；pytest 同时调用后端与独立技能验证并比较问题码、严重度及镜头。',
              '该报告测量固定故障族的离线规则覆盖，不是开放域准确率，也不代表真实模型端到端验收。']
    if result['misses'] or result['false_positives']:
        lines += ['', '未通过详情：', str(result['misses']), str(result['false_positives'])]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> int:
    result = score()
    write_report(result, Path(__file__).with_name('report.md'))
    print(f"故障召回 {result['caught']}/{result['total']}，正确样本误报 {len(result['false_positives'])}/{result['correct_total']}")
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
