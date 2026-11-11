"""生成无外链、可离线审阅的单文件 HTML。"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from eval_support import (GROUPS, LABELS, METRICS, METRIC_LABELS, formatted, read_json,
                          resolved, run_folder, run_ids, select_cases, summarize)


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def panel(case: dict, folder: Path, group: str, judge: dict) -> str:
    parts = [f'<article><h3>{LABELS[group]}</h3>']
    try:
        shotlist = read_json(folder / 'shotlist.json')
        expanded = resolved(case, folder)['shots']
        lines = {s['id']: s['narration_resolved'] for s in expanded}
        parts += ['<h4>展开台词</h4>']
        for shot in shotlist['shots']:
            parts.append(f'<p><b>{escape(shot["id"])}</b> {escape(lines[shot["id"]])}</p>')
        parts.append('<h4>镜头表</h4><table><tr><th>镜头</th><th>类型 / 来源</th><th>秒</th><th>参数与引用</th></tr>')
        for shot in shotlist['shots']:
            detail = json.dumps({'事实': shot.get('fact_refs', []), '类比': shot.get('analogy_refs', []),
                                 '素材': shot.get('asset_refs', []), '画面参数': shot.get('params', {})}, ensure_ascii=False)
            parts.append(f'<tr><td>{escape(shot["id"])}</td><td>{escape(shot["kind"])} / {escape(shot["source"])}</td><td>{escape(shot["duration_s"])}</td><td>{escape(detail)}</td></tr>')
        parts.append('</table>')
        validation = read_json(folder / 'validation-report.json')
        parts.append('<h4>阻断与警告</h4>')
        issues = [i for i in validation['issues'] if i['severity'] in {'block', 'warn'} or i['code'] == 'CHECK_ERROR']
        for issue in issues:
            parts.append(f'<p class="{escape(issue["severity"])}"><b>{escape(issue["code"])}</b> · {escape(issue.get("shot") or "全片")} · {escape(issue["message"])}<br>{escape(issue.get("fix", issue.get("hint", "")))}</p>')
        if not issues:
            parts.append('<p>无阻断与警告。</p>')
        for issue in validation.get('input_errors', []):
            parts.append(f'<p class="block">格式错误：{escape(issue)}</p>')
        grade = read_json(folder / 'grading.json')
        audit = grade.get('traceability', {})
        rate = audit.get('rate')
        parts.append('<h4>可溯源率</h4><p>' + (f"{rate:.1%}（{audit['supported']}/{audit['total']}）" if rate is not None else '未完成') + '</p>')
        for claim in audit.get('claims', []):
            if not claim['supported']:
                parts.append(f'<p class="warn">待核实：{escape(claim["shot"])} · {escape(claim["text"])}</p>')
        parts.append(f'<h4>断言：{escape(grade["status"])}</h4>')
        for assertion in grade['assertions']:
            parts.append(f'<p>{"通过" if assertion["passed"] else "失败"} · {escape(assertion["id"])} {escape(assertion.get("error") or "")}</p>')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parts.append(f'<p class="block">产物或评分未完成：{escape(exc)}</p>')
    parts.append('<h4>文采评分</h4>')
    if judge.get('status') == '已评分':
        scores = judge['groups'][group]
        parts.append('<p>' + '；'.join(f'{name} {scores[key]}/5' for key, name in zip(METRICS, METRIC_LABELS)) + '</p>')
    else:
        parts.append('<p>未完成；无有效盲评结果。</p>')
    delivery = folder / 'delivery-report.md'
    if delivery.exists():
        parts.append('<details><summary>模型交付说明</summary><pre>' + escape(delivery.read_text(encoding='utf-8')) + '</pre></details>')
    parts.append('</article>')
    return ''.join(parts)


def generate(output: Path, only: str | None = None) -> Path:
    summary = summarize(output)
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>分镜技能评测报告</title><style>body{font:16px/1.6 system-ui,sans-serif;margin:28px;color:#203044;background:#f5f7fa}h1,h2{color:#13263d}table{border-collapse:collapse;width:100%;background:white}td,th{padding:8px;border:1px solid #cbd4df;text-align:left;overflow-wrap:anywhere}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{min-width:0;padding:20px;background:white;border:1px solid #d6dde7;border-radius:8px}.block{color:#a32121}.warn{color:#895600}pre{white-space:pre-wrap;overflow-wrap:anywhere}section{margin-top:36px}@media(max-width:850px){.pair{grid-template-columns:1fr}body{margin:12px}}</style>',
             '<h1>分镜技能评测报告</h1><p>真实性与文采分别评价；未运行或失败不算通过。此页面无外链，数据全部内嵌。</p>',
             '<p>' + escape(summary['note']) + '</p><h2>顶部汇总</h2>',
             '<table><tr><th>场景 / 组别</th><th>完成 / 预期</th><th>阻断</th><th>警告</th><th>断言通过率</th><th>可溯源率</th><th>文采均分</th><th>胜率</th></tr>']
    for row in summary['rows']:
        if only and row['case'] != only:
            continue
        parts.append('<tr><td>' + escape(row['case'] + ' / ' + LABELS[row['group']]) + '</td><td>' + f'{row["completed"]}/{row["expected"]}' + '</td>' + ''.join('<td>' + formatted(row[k], k in {'win_rate', 'assertion_rate', 'traceability_rate'}) + '</td>' for k in ('block', 'warn', 'assertion_rate', 'traceability_rate', 'prose', 'win_rate')) + '</tr>')
    parts.append('</table>')
    for group, row in summary['overall'].items():
        prose = f'{row["prose"]:.2f}' if row['prose'] is not None else '未完成'
        wins = f'{row["win_rate"]:.1%}' if row['win_rate'] is not None else '未完成'
        parts.append(f'<p>{LABELS[group]}：文采均分 {prose}，胜率 {wins}，有效盲评 {row["judged"]} / 预期 {row["expected"]}。</p>')
    for case in select_cases(only):
        for run in run_ids(output, case['name']):
            path = output / case['name'] / f'judge-{run}.json'
            judge = read_json(path) if path.exists() else {}
            winner = LABELS.get(judge.get('winner_group'), '平局' if judge.get('winner_group') == 'tie' else '未完成')
            parts.append(f'<section><h2>{escape(case["name"])} · 第 {run} 次</h2><p>{escape(case["prompt"])}</p><p>盲评胜者：{winner}。{escape(judge.get("reason", judge.get("error", "")))}</p><div class="pair">')
            parts.extend(panel(case, run_folder(output, case['name'], group, run), group, judge) for group in GROUPS)
            parts.append('</div></section>')
    parts.append('</html>')
    target = output / 'report.html'
    target.write_text(''.join(parts), encoding='utf-8')
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='生成单文件离线报告；本脚本始终不调用模型。')
    parser.add_argument('--iteration', type=Path, help='iteration-N 目录')
    parser.add_argument('--score-only', type=Path, help='从此轮既有结果重建报告，不调用模型')
    parser.add_argument('--only', help='仅展示指定场景')
    args = parser.parse_args(argv)
    output = args.score_only or args.iteration
    if output is None or not output.is_dir():
        parser.error('请指定有效轮次目录')
    try:
        print(f'报告已生成：{generate(output.resolve(), args.only)}')
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
