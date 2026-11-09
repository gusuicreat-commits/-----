"""生成可离线打印的镜头与参数溯源报告。"""
import base64
from datetime import datetime, timezone
import html
import json
import re
import time

from app import events, llm, storage
from .text import PLACEHOLDER, format_value
from .timeline import references

STATUS = {"verified": "已核验", "confirmed": "人工确认", "needs_review": "待确认", "rejected": "已否决"}
REVIEW = {"pending": "待复核", "approved": "已通过", "changes": "需修改"}
KINDS = {"title": "开场", "model_orbit": "模型环绕", "analogy": "尺寸类比", "motion": "运动演示",
         "exploded": "结构拆解", "data_card": "参数卡片", "real_media": "实拍素材", "ai_broll": "创意画面",
         "weld_macro": "焊缝特写", "outro": "结尾"}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _source(fact: dict) -> str:
    source = fact.get("source", {})
    return f"{source.get('doc', '出处缺失')} 第{source.get('page', '？')}页：{source.get('quote', '')}"


def _unsourced(text: str) -> str:
    parts, position = [], 0
    for match in re.finditer(r"\d+(?:\.\d+)?", text):
        parts.append(_escape(text[position:match.start()]))
        parts.append('<mark title="无参数出处">' + _escape(match[0]) + '</mark>')
        position = match.end()
    return "".join(parts) + _escape(text[position:])


def _narration(template: str, facts: dict, analogies: dict) -> str:
    parts, position = [], 0
    for match in PLACEHOLDER.finditer(template):
        # 没有占位出处的数字也显式标注，强制生成时不能伪装成已核验。
        parts.append(_unsourced(template[position:match.start()]))
        key = match[1]
        fact = facts.get(key)
        if fact:
            label, source = format_value(fact["value"], fact["unit"]), _source(fact)
        elif key in analogies:
            analogy = analogies[key]
            label = analogy["text"]
            source = _source(facts.get(analogy["fact"], {})) + "；" + analogy.get("formula", "") + "；" + analogy.get("basis", "")
        else:
            label, source = match[0], "引用缺失，待人工确认"
        parts.append(f'<mark title="{_escape(source)}">{_escape(label)}</mark>')
        position = match.end()
    parts.append(_unsourced(template[position:]))
    return "".join(parts)


def _durations(pid: str, run: dict) -> dict:
    result = dict(run.get("stage_durations_s", {}))
    grouped: dict[str, list[float]] = {}
    for event in events.read_events(pid):
        if event["run"] == run.get("run"):
            grouped.setdefault(event["stage"], []).append(datetime.fromisoformat(event["ts"]).timestamp())
    for stage, values in grouped.items():
        result.setdefault(stage, round(max(values) - min(values), 3))
    return result


def build_report(pid: str) -> dict:
    started = time.monotonic()
    project = storage.read_json(pid, "project.json")
    run = storage.read_json(pid, "run.json", {})
    with events.tool_call(pid, run.get("run", "report"), "report", "report.provenance", "正在生成溯源报告") as call:
        directory = storage.project_dir(pid)
        timeline = storage.read_json(pid, "timeline.json", {"shots": [], "facts": {}, "analogies": {}, "assets": {}})
        shotlist = storage.read_json(pid, "shotlist.json", {"shots": []})
        originals = {shot["id"]: shot for shot in shotlist["shots"]}
        facts = timeline.get("facts", {})
        analogies = timeline.get("analogies", {})
        issues = storage.read_json(pid, "issues.json", {"issues": []})["issues"]
        logs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((directory / "llm").glob("*.json"))]
        known_costs = [log["cost_usd"] for log in logs if isinstance(log.get("cost_usd"), (float, int))]
        model = project.get("model") or {}
        rig = storage.read_json(pid, "model/rig.json", {})
        report = {"project": {"id": pid, "name": project["name"]}, "generated_at": datetime.now(timezone.utc).isoformat(),
                  "duration_s": timeline.get("rendered_duration_s", timeline.get("duration_s", 0)),
                  "runtime_model": llm.MODEL, "run": run.get("run"), "forced": run.get("forced", False),
                  "stage_durations_s": _durations(pid, run),
                  "llm": {"calls": len(logs), "cost_usd": sum(known_costs), "unknown_cost_calls": len(logs) - len(known_costs),
                          "scope": "项目全部调用"},
                  "facts": [{**f, "status_label": STATUS.get(f.get("status"), "待确认")} for f in facts.values()],
                  "model": {**model, "derived_from": model.get("derived_from", rig.get("derived_from", [])),
                            "assumed": model.get("assumed", [])},
                  "issues": issues, "issues_by_severity": {level: [i for i in issues if i["severity"] == level]
                                                            for level in ("block", "warn", "info")},
                  "has_unresolved_blocks": any(i["severity"] == "block" for i in issues),
                  "music": timeline.get("music"), "shots": [], "assets": []}
        used_assets = set()
        for shot in timeline["shots"]:
            original = originals.get(shot["id"], shot)
            aids = set(original.get("asset_refs", []))
            if shot["params"].get("asset"):
                aids.add(shot["params"]["asset"])
            assets = [timeline["assets"][aid] for aid in sorted(aids) if aid in timeline.get("assets", {})]
            used_assets.update(aids)
            a_refs = set(original.get("analogy_refs", [])) | {shot["params"].get("analogy")}
            a_refs.update(k for k in PLACEHOLDER.findall(original.get("narration", "")) if k.startswith("A_"))
            frame = storage.safe_path(directory / "renders/frames_qa", f"{shot['id']}.png")
            thumbnail = "data:image/png;base64," + base64.b64encode(frame.read_bytes()).decode("ascii") if frame.is_file() else None
            report["shots"].append({**shot, "thumbnail": thumbnail, "narration_template": original.get("narration", ""),
                                    "fact_refs": sorted(references(original, analogies, rig)),
                                    "analogies": [analogies[aid] for aid in sorted(a for a in a_refs if a) if aid in analogies],
                                    "assets": assets, "review": original.get("review", {"status": "pending", "note": ""}),
                                    "issues": [i for i in issues if i.get("shot") in {None, shot["id"]}]})
        report["assets"] = [timeline["assets"][aid] for aid in sorted(used_assets) if aid in timeline.get("assets", {})]
        report["stage_durations_s"]["report"] = round(time.monotonic() - started, 4)
        body = [f'<h1>{_escape(project["name"])} · 溯源报告</h1>',
                f'<p>生成时间：{_escape(report["generated_at"])}　成片时长：{report["duration_s"]:.2f} 秒</p>',
                f'<p>运行时模型：{_escape(llm.MODEL)}　大模型调用：{len(logs)} 次（项目累计）　已知费用合计：${sum(known_costs):.4f}</p>']
        if report["llm"]["unknown_cost_calls"]:
            body.append(f'<p>有 {report["llm"]["unknown_cost_calls"]} 次调用未提供费用，未计入合计。</p>')
        if report["has_unresolved_blocks"]:
            body.append('<p class="block">存在未处理的阻断问题' + ('；本次已强制继续生成。' if report["forced"] else '。') + '</p>')
        names = dict(zip(("ingest", "model", "plan", "validate", "tts", "render", "compose", "qa", "report"),
                         ("资料提取", "模型准备", "分镜规划", "参数校验", "配音", "渲染", "合成", "画面质检", "报告")))
        body.append('<p>各阶段耗时：' + '；'.join(f'{names.get(k, k)} {v:.3f} 秒' for k, v in report["stage_durations_s"].items()) + '</p>')
        body.append('<h2>参数来源</h2><table><tr><th>参数</th><th>数值</th><th>状态</th><th>文档</th><th>页码</th><th>原文摘录</th></tr>')
        for fact in report["facts"]:
            source = fact.get("source", {})
            body.append('<tr>' + ''.join(f'<td>{_escape(v)}</td>' for v in
                        (fact["name"], format_value(fact["value"], fact["unit"]), fact["status_label"], source.get("doc", "待补充"),
                         source.get("page", "待补充"), source.get("quote", "待补充"))) + '</tr>')
        body.append('</table><h2>镜头溯源</h2><table><tr><th>画面 / 时间</th><th>台词与依据</th><th>复核与问题</th></tr>')
        for shot in report["shots"]:
            picture = f'<img src="{shot["thumbnail"]}" alt="镜头 {_escape(shot["id"])}">' if shot["thumbnail"] else '<p>暂无质检帧</p>'
            body.append(f'<tr><td>{picture}<p>{_escape(shot["id"])}　{shot["start"]:.2f}–{shot["end"]:.2f} 秒</p>'
                        f'<p>{KINDS.get(shot["kind"], _escape(shot["kind"]))} · {_escape(shot["badge"])}</p></td><td>'
                        + _narration(shot["narration_template"], facts, analogies))
            for fid in shot["fact_refs"]:
                if fid in facts:
                    body.append(f'<p class="note">{_escape(facts[fid]["name"])}：{_escape(_source(facts[fid]))}</p>')
            for analogy in shot["analogies"]:
                body.append(f'<p>类比：{_escape(analogy.get("formula", ""))}；{_escape(analogy.get("basis", ""))}</p>')
            for asset in shot["assets"]:
                body.append(f'<p>素材署名：{_escape(asset.get("credit", ""))}</p>')
            body.append(f'</td><td>{REVIEW.get(shot["review"]["status"], "待复核")}<p>{_escape(shot["review"].get("note", ""))}</p>'
                        + ''.join(f'<p>{_escape(i["message"])}</p>' for i in shot["issues"]) + '</td></tr>')
        body.append('</table><h2>三维模型</h2>')
        body.append(f'<p>类型：{ {"step": "STEP 导入", "parametric": "参数化重建"}.get(model.get("kind"), "未提供") }；STEP 文件：{_escape(model.get("step", "无"))}</p>')
        body.append('<p>参数化依据：' + _escape('、'.join(report["model"]["derived_from"])) + '</p><p>默认假设：'
                    + _escape('、'.join(report["model"]["assumed"])) + '</p>')
        for check in model.get("dims_check", []):
            body.append(f'<p>{_escape(check.get("fact", ""))}：模型 {_escape(check.get("model_value"))}，文档 {_escape(check.get("doc_value"))}，'
                        + ('通过' if check.get("ok") else '未通过') + f' {_escape(check.get("message", ""))}</p>')
        body.append('<h2>问题清单</h2>')
        for level, label in (("block", "阻断"), ("warn", "警告"), ("info", "提示")):
            body.append(f'<h3>{label}</h3>')
            items = report["issues_by_severity"][level]
            body.extend(f'<p>{_escape(i["id"])} {_escape(i.get("shot") or "全片")}：{_escape(i["message"])}；{_escape(i.get("hint", ""))}</p>' for i in items)
            if not items:
                body.append('<p>无</p>')
        body.append('<h2>素材与配乐署名</h2>')
        for item in report["assets"] + ([report["music"]] if report["music"] else []):
            body.append(f'<p>{_escape(item.get("title", ""))}：{_escape(item.get("credit", ""))}</p>')
        css = 'body{font:14px/1.6 sans-serif;color:#17212b;margin:32px}table{width:100%;border-collapse:collapse}td,th{border:1px solid #ccd2d9;padding:8px;text-align:left;vertical-align:top}td:first-child{min-width:130px}img{width:200px;max-width:100%}mark{background:#fff0a8}.block{border:3px solid #b51c20;color:#b51c20;padding:12px;font-weight:bold}.note{font-size:12px;color:#445}tr{break-inside:avoid}h2{break-after:avoid}@media print{body{margin:0;font-size:10pt}thead{display:table-header-group}img{width:150px}}'
        document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>溯源报告</title><style>' + css + '</style><body>' + ''.join(body) + '</body></html>'
        storage.write_json(pid, "report.json", report)
        (directory / "report.html").write_text(document, encoding="utf-8")
        call.ok(f"溯源报告已生成，包含 {len(report['shots'])} 个镜头和 {len(facts)} 条参数")
    return report
