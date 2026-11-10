"""逐项检查分镜；局部坏数据不阻断其余校验。"""
from contextlib import contextmanager
import math
import re
from typing import Any, Iterator

from _rules import PARAM_DEFAULTS, expected_source, motion_speedup
from resolve_text import PLACEHOLDER, find_duplicate_phrases, find_unsourced_numbers, resolve

EQUIPMENT = re.compile(r"起重机|门机|龙门吊|吊车|主梁|支腿|吊钩|小车|crane|gantry|hook|girder", re.I)


def validate(facts_data: dict, shotlist: dict, assets_data: dict | None = None,
             project: dict | None = None, rig: dict | None = None) -> dict:
    result: dict[str, list[dict]] = {"issues": []}

    def add(code: str, severity: str, message: str, hint: str, shot: str | None = None) -> None:
        result["issues"].append({"id": f"I{len(result['issues']) + 1}", "shot": shot,
                                 "severity": severity, "code": code, "message": message, "hint": hint})

    @contextmanager
    def check(label: str, sid: str | None = None) -> Iterator[None]:
        try:
            yield
        except Exception:
            add("CHECK_ERROR", "info", f"{label}检查未完成，输入数据或存储格式异常", "检查对应字段后重新校验", sid)

    has_project, has_rig = project is not None, rig is not None
    project = project if project is not None else {}
    assets_data = assets_data if assets_data is not None else {"assets": []}
    rig = rig if rig is not None else {"axes": {}}
    facts, assets, analogies = {}, {}, {}
    shots: list[dict] = []
    model = None
    with check("项目模型"):
        model = project.get("model")
    for label, data, key, dest in (("参数表", facts_data, "facts", facts), ("素材库", assets_data, "assets", assets),
                                    ("类比表", shotlist, "analogies", analogies)):
        with check(label):
            for item in data.get(key, []):
                with check(label + "条目"):
                    dest[item["id"]] = item
    with check("镜头列表"):
        if not isinstance(shotlist["shots"], list):
            raise ValueError("镜头列表格式无效")
        shots = shotlist["shots"]

    total = 0.0
    pending = 0
    for index, shot in enumerate(shots, 1):
        sid = f"S{index}"
        if not isinstance(shot, dict):
            add("CHECK_ERROR", "info", "镜头条目格式无效", "镜头应为对象", sid)
            continue
        sid = shot.get("id", sid)
        narration = shot.get("narration", "")
        params = shot.get("params", {})
        kind = shot.get("kind")
        with check("参数引用", sid):
            refs = list(shot.get("fact_refs", []))
            refs += [key for key in PLACEHOLDER.findall(narration) if key.startswith("F_")]
            refs += params.get("facts", [])
            if params.get("fact"):
                refs.append(params["fact"])
            aids = list(shot.get("analogy_refs", []))
            aids += [key for key in PLACEHOLDER.findall(narration) if key.startswith("A_")]
            if params.get("analogy"):
                aids.append(params["analogy"])
            refs += [analogies[aid]["fact"] for aid in aids if aid in analogies]
            for fid in dict.fromkeys(refs):
                fact = facts.get(fid)
                if fact is None:
                    add("UNKNOWN_FACT", "block", f"引用了不存在的参数：{fid}", "改用参数表中已有的可引用参数", sid)
                elif fact.get("status") == "rejected":
                    add("REJECTED_FACT", "block", f"参数已被人工否决：{fid}", "删除引用或重新核实参数", sid)
                elif fact.get("status") not in {"verified", "confirmed"}:
                    add("UNVERIFIED_FACT", "warn", f"参数尚待核验：{fid}", "核实原文后人工确认参数", sid)
        with check("台词数字", sid):
            for fragment in find_unsourced_numbers(PLACEHOLDER.sub("", narration)):
                add("UNSOURCED_NUMBER", "block", f"台词出现无出处的数字「{fragment}」", "改用 {{F_xxx}} 占位或删除", sid)
        with check("类比引用", sid):
            aids = list(shot.get("analogy_refs", []))
            aids += [key for key in PLACEHOLDER.findall(narration) if key.startswith("A_")]
            for aid in dict.fromkeys(aids):
                if aid not in analogies:
                    add("ANALOGY_MISSING", "block", f"引用的类比不存在：{aid}", "登记类比请求并重新计算", sid)
            if (kind == "analogy" or params.get("analogy")) and params.get("analogy") not in analogies:
                add("ANALOGY_PARAM", "block", "镜头画面引用的类比不存在", "为 params.analogy 选择已计算的类比", sid)
        with check("创意镜头设备词", sid):
            if kind == "ai_broll" and EQUIPMENT.search(params.get("prompt", "") + " " + params.get("caption", "")):
                add("AI_SHOWS_EQUIPMENT", "block", "创意画面描述含设备本体或结构词", "改为光影、环境或抽象转场；设备使用模型或实拍", sid)
        with check("镜头来源", sid):
            if kind not in PARAM_DEFAULTS or shot.get("source") != expected_source(kind, model):
                add("SOURCE_MISMATCH", "block", "镜头类型与画面来源不一致", "按镜头类型设置 model、real、ai 或 graphic", sid)
        with check("运动参数", sid):
            if kind == "motion" and has_rig:
                params.pop("speedup", None)
                axis = params.get("axis")
                if axis not in rig["axes"]:
                    add("MOTION_AXIS_UNAVAILABLE", "block", f"模型未提供运动轴：{axis}", "选择 rig 中已存在的运动轴", sid)
                else:
                    speed_fact = facts.get(rig["axes"][axis].get("speed_fact"), {})
                    speed = speed_fact.get("value")
                    sourced = (speed_fact.get("status") in {"verified", "confirmed"}
                               and speed_fact.get("unit") == "m/min" and isinstance(speed, (int, float))
                               and math.isfinite(speed) and speed > 0)
                    if not sourced:
                        params["speedup"] = 1
                        add("MOTION_SPEED_UNSOURCED", "warn", "运动速度没有可引用的参数，倍速暂记为 1", "核验 rig.speed_fact 对应的速度参数", sid)
                    motion = motion_speedup(rig, axis, params["from_m"], params["to_m"], shot["duration_s"], speed if sourced else 1)
                    if "error" in motion:
                        add("MOTION_OUT_OF_RANGE", "block", "运动参数无效：" + motion["error"], "将起终点设在行程内，并使用有效时长", sid)
                    else:
                        params["speedup"] = motion["speedup"] if sourced else 1
        with check("素材引用", sid):
            refs = list(shot.get("asset_refs", []))
            if kind == "real_media":
                refs.append(params.get("asset", ""))
            for aid in dict.fromkeys(refs):
                asset = assets.get(aid)
                if asset is None:
                    add("ASSET_MISSING", "block", f"引用的实拍素材不存在：{aid}", "选择素材库中的有效素材", sid)
                elif asset.get("provenance") == "reference" and any(word in narration for word in ("这台", "本机", "我们的")):
                    add("REFERENCE_ASSET_CLAIM", "warn", "参考实拍台词暗示画面为本设备", "改为「像这样的造船门机」等泛指表述", sid)
        with check("台词解析", sid):
            shot["narration_resolved"] = resolve(narration, facts, analogies)
        with check("台词重复短语", sid):
            duplicates = find_duplicate_phrases(shot["narration_resolved"])
            if duplicates:
                add("DUPLICATE_PHRASE", "block", "台词含重复或冗余短语：" + "、".join(f"「{p}」" for p in duplicates),
                    "删除占位前后多余的修饰词", sid)
        with check("台词时长", sid):
            if len(shot["narration_resolved"]) / 4.5 > shot["duration_s"] + 1:
                add("NARRATION_TOO_LONG", "warn", "台词预计朗读时间超出镜头时长", "缩短台词或延长镜头", sid)
        with check("镜头时长", sid):
            duration = float(shot["duration_s"])
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("时长无效")
            total += duration
        with check("人工复核状态", sid):
            pending += shot.get("review", {}).get("status") == "pending"
    with check("写实分镜偏好"):
        if project.get("render_mode") == "photoreal":
            valid = [s for s in shots if isinstance(s, dict)]
            kinds = [s.get("kind") for s in valid]
            first = valid[0] if valid else {}
            if first.get("kind") != "model_orbit" or "girder" not in first.get("params", {}).get("highlight", []):
                add("PHOTOREAL_OPENING", "warn", "写实开场建议用主梁高亮的整机环绕", "首镜头使用 model_orbit，highlight 包含 girder")
            if "real_media" in kinds and (len(kinds) < 2 or kinds[1] != "real_media"):
                add("PHOTOREAL_REAL_MEDIA_ORDER", "warn", "写实片中的实拍未放在第二镜头", "将首个 real_media 放在第二镜头")
            for kind, label in (("exploded", "结构分解"), ("motion", "运动演示")):
                if kind not in kinds:
                    add("PHOTOREAL_MISSING_" + kind.upper(), "warn", f"写实片缺少{label}镜头", f"至少安排一个 {kind} 镜头")
            if sum(k in {"model_orbit", "exploded", "motion", "title"} for k in kinds) < 3:
                add("PHOTOREAL_MODEL_COUNT", "warn", "写实模型镜头合计少于三个", "增加环绕、结构分解或运动镜头")
            if kinds.count("analogy") > 1:
                add("PHOTOREAL_ANALOGY_COUNT", "warn", "写实片的类比镜头超过一个", "保留一个最直观的类比镜头")
    with check("模型尺寸"):
        for item in (model or {}).get("dims_check", []):
            if item.get("ok") is False:
                add("MODEL_DIMS_MISMATCH", "warn", item.get("message", "模型尺寸与文档参数不一致"), "核实模型单位、方向及尺寸")
    with check("模型默认值"):
        if model and model.get("kind") == "parametric" and model.get("assumed"):
            add("MODEL_ASSUMED", "info", "参数化重建使用默认值：" + "、".join(model["assumed"]), "补充并核验这些参数后重建模型")
    if not 30 <= total <= 60:
        add("DURATION_OUT_OF_RANGE", "warn", f"分镜总时长 {total:g} 秒，不在 30–60 秒范围内", "调整镜头数量或时长")
    if pending:
        add("NOT_REVIEWED", "info", f"有 {pending} 个镜头尚未人工复核", "逐镜头检查台词、画面和出处")
    return enrich_report(result, facts_data, shotlist, has_project, has_rig, project, rig, assets_data)


FIXES: dict[str, tuple[str, str]] = {
    'UNKNOWN_FACT': ('fact_refs/narration/params', '删除不存在的参数引用，并在 narration、fact_refs、params.facts、params.fact 及相关类比中改用同一已确认参数 ID'),
    'REJECTED_FACT': ('fact_refs/narration/params', '移除被否决参数的台词、画面字段及关联类比；需要恢复时先让人工核实原始文档'),
    'UNVERIFIED_FACT': ('fact_refs/narration/params', '暂时移除该参数的所有引用，将缺失内容列入人工确认项；不得自行改写 facts.status'),
    'UNSOURCED_NUMBER': ('narration', '将 message 指出的数字替换为已确认参数的 {{F_id}} 或计算后的 {{A_id}}；无对应参数则删去该数值断言'),
    'ANALOGY_MISSING': ('analogy_refs/narration', '为指出的 A_id 登记 fact/ref/axis 请求，运行 compute_analogy.py，将结果写入 analogies 并对齐 analogy_refs 与台词占位符'),
    'ANALOGY_PARAM': ('params.analogy', '从已计算的 analogies[].id 中选择 ID 填入 params.analogy；没有可用参数时改为非类比镜头'),
    'AI_SHOWS_EQUIPMENT': ('params.prompt/params.caption', '逐项移除 prompt 和 caption 内的设备本体词，改写为光影或环境；需展示设备时改用 model_orbit/source=model 或 real_media/source=real'),
    'SOURCE_MISMATCH': ('kind/source', '按 kind 修正 source：ai_broll=ai、real_media=real；无模型的 title/outro/data_card=graphic，其余为 model'),
    'MOTION_AXIS_UNAVAILABLE': ('params.axis', '从提供的 rig.axes 键中选择轴；没有合适轴时改为静态 model_orbit 并重写 params'),
    'MOTION_SPEED_UNSOURCED': ('params.speedup/rig.axes', '核实所选轴 speed_fact 对应事实，要求 verified/confirmed、unit=m/min、value>0；重跑校验计算倍速，不手填速度'),
    'MOTION_OUT_OF_RANGE': ('params.from_m/params.to_m/duration_s', '将 from_m、to_m 改到所选 rig.axes[axis].range_m 内，duration_s 改为有限正数，再重跑以计算 speedup'),
    'ASSET_MISSING': ('asset_refs/params.asset', '把不存在的素材 ID 替换为 assets[].id 的有效值，并同步 asset_refs 与 real_media.params.asset'),
    'REFERENCE_ASSET_CLAIM': ('narration', '将台词里的「这台」「本机」「我们的」逐一改为「像这样的造船门机」等泛指；保留参考实拍来源标签'),
    'DUPLICATE_PHRASE': ('narration', '按 message 删除重复词；若来自类比占位符，只保留 {{A_id}}，删除它前后的「相当于/大约/那么高」等重复修饰'),
    'NARRATION_TOO_LONG': ('narration/duration_s', '缩短该镜头展开后的台词，或把 duration_s 调至展开字数/4.5+0.8 秒；同时保持全片目标时长'),
    'DURATION_OUT_OF_RANGE': ('shots[].duration_s', '调整各镜头 duration_s，使总时长落在 30–60 秒内，并满足需求时长'),
    'NOT_REVIEWED': ('shots[].review.status', '请人工逐镜头复核台词、画面来源和出处；仅人工确认后更新 review.status，自动检查不代替人工批准'),
    'MODEL_DIMS_MISMATCH': ('project.model.dims_check', '请模型负责人核实尺寸单位、坐标轴和来源文档，修正模型并重新生成 dims_check；不要手改 ok 消除问题'),
    'MODEL_ASSUMED': ('project.model.assumed', '请人工补充并确认列出的缺失参数，再重建模型；保持默认值标记直到重建完成'),
    'PHOTOREAL_OPENING': ('shots[0].kind/params.highlight', '把首镜头设为 model_orbit、source=model，并在 params.highlight 包含 girder'),
    'PHOTOREAL_REAL_MEDIA_ORDER': ('shots', '将首个 real_media 移至第二镜头，保留原镜头 id 和人工台词'),
    'PHOTOREAL_MISSING_EXPLODED': ('shots[].kind', '增加或改设一个 exploded/source=model 镜头，params.parts 仅用已知节点，并重新分配时长'),
    'PHOTOREAL_MISSING_MOTION': ('shots[].kind', '取得真实 rig 后增加一个 motion/source=model 镜头；设置有效 axis/from_m/to_m；缺 rig 时交人工确认，不编造行程'),
    'PHOTOREAL_MODEL_COUNT': ('shots[].kind', '使 model_orbit、exploded、motion、title 合计至少三个，并保持全片目标时长'),
    'PHOTOREAL_ANALOGY_COUNT': ('shots[].kind', '仅保留一个最直观的 analogy，将其余类比镜头改为结构或参数展示并清理不再使用的引用'),
    'CHECK_ERROR': ('input', '按 message 定位检查阶段，修正相关字段类型及缺失字段，重跑校验；不得把此条 info 当作已检查通过'),
}


def issue_fields(issue: dict, shot: dict) -> str:
    """细化到实际触发字段，不改变问题数量和严重度。"""
    code = issue['code']
    params = shot.get('params') or {}
    if not isinstance(params, dict):
        params = {}
    fields = []
    if code in {'UNKNOWN_FACT', 'REJECTED_FACT', 'UNVERIFIED_FACT'}:
        fid = issue['message'].rsplit('：', 1)[-1]
        for index, ref in enumerate(shot.get('fact_refs') or []):
            if ref == fid:
                fields.append(f'fact_refs[{index}]')
        if '{{' + fid + '}}' in str(shot.get('narration', '')):
            fields.append('narration')
        for index, ref in enumerate(params.get('facts') or []):
            if ref == fid:
                fields.append(f'params.facts[{index}]')
        if params.get('fact') == fid:
            fields.append('params.fact')
        if not fields:
            fields.append('analogy_refs/params.analogy/analogies[].fact')
    elif code == 'AI_SHOWS_EQUIPMENT':
        fields = [f'params.{key}' for key in ('prompt', 'caption')
                  if isinstance(params.get(key), str) and EQUIPMENT.search(params[key])]
    elif code == 'ASSET_MISSING':
        aid = issue['message'].rsplit('：', 1)[-1]
        fields = [f'asset_refs[{index}]' for index, ref in enumerate(shot.get('asset_refs') or []) if ref == aid]
        if shot.get('kind') == 'real_media' and params.get('asset', '') == aid:
            fields.append('params.asset')
    elif code == 'SOURCE_MISMATCH':
        fields = ['kind' if shot.get('kind') not in PARAM_DEFAULTS else 'source']
    elif code == 'CHECK_ERROR':
        label = issue['message'].split('检查未完成')[0]
        fields = [{'参数引用': 'fact_refs/analogy_refs/params', '台词数字': 'narration',
                   '类比引用': 'analogy_refs/params.analogy', '运动参数': 'params/duration_s/rig.axes',
                   '台词解析': 'narration/facts/analogies', '台词时长': 'narration/duration_s',
                   '镜头时长': 'duration_s', '素材引用': 'asset_refs/params.asset',
                   '人工复核状态': 'review', '镜头列表': 'shots'}.get(label, 'input')]
    return '/'.join(fields) if fields else FIXES[code][0]


def enrich_report(result: dict, facts_data: dict, shotlist: dict, has_project: bool, has_rig: bool,
                  project: dict, rig: dict, assets_data: dict) -> dict:
    raw_shots = shotlist.get('shots', []) if isinstance(shotlist, dict) else []
    shots = {s.get('id', f'S{index}'): s for index, s in enumerate(raw_shots or [], 1)
             if isinstance(s, dict) and isinstance(s.get('id', f'S{index}'), str)} if isinstance(raw_shots, list) else {}
    for issue in result['issues']:
        _, fix = FIXES[issue['code']]
        shot = shots.get(issue['shot'], {}) if isinstance(issue['shot'], str) else {}
        try:
            field = issue_fields(issue, shot)
        except (TypeError, AttributeError):
            field = FIXES[issue['code']][0]
        if issue['code'] == 'SOURCE_MISMATCH' and shot.get('kind') in PARAM_DEFAULTS:
            fix += f"；此镜头 source 应为 {expected_source(shot['kind'], project.get('model'))}"
        if issue['code'] == 'MOTION_AXIS_UNAVAILABLE' and isinstance(rig.get('axes'), dict):
            fix += '；本输入可选轴：' + ('、'.join(rig['axes']) or '无，需补充真实运动配置')
        if issue['code'] == 'MOTION_OUT_OF_RANGE' and isinstance(rig.get('axes'), dict):
            axis = (shot.get('params') or {}).get('axis')
            fix += f"；轴 {axis} 的有效范围为 {rig['axes'].get(axis, {}).get('range_m')} 米"
        issue['field'] = field
        location = f"镜头 {issue['shot']} 的 {field}" if issue['shot'] else field
        issue['fix'] = f"{location}：{fix}。触发内容：{issue['message']}"
    skipped = []
    if not has_project:
        skipped.append({'codes': ['MODEL_DIMS_MISMATCH', 'MODEL_ASSUMED'], 'reason': '未提供 --project 模型元数据，无法核实尺寸或默认值；来源规则按未提供模型处理'})
    if not has_rig:
        skipped.append({'codes': ['MOTION_AXIS_UNAVAILABLE', 'MOTION_SPEED_UNSOURCED', 'MOTION_OUT_OF_RANGE'], 'reason': '未提供 --rig，跳过运动轴、行程、速度及倍速计算；运动镜头交付前必须提供真实 rig'})
    result['skipped'] = skipped
    result['manual_review'] = [
        {'fact': f.get('id'), 'status': f.get('status'), 'message': '该参数不可引用，请人工核实原文；本报告不修改参数状态'}
        for f in facts_data.get('facts', []) if isinstance(f, dict) and f.get('status') not in {'verified', 'confirmed'}
    ] if isinstance(facts_data, dict) and isinstance(facts_data.get('facts'), list) else []
    result['counts'] = {level: sum(i['severity'] == level for i in result['issues']) for level in ('block', 'warn', 'info')}
    result['passed'] = not result['counts']['block'] and not any(i['code'] == 'CHECK_ERROR' for i in result['issues'])
    result['summary'] = f"真实性校验：{result['counts']['block']} 个阻断、{result['counts']['warn']} 个警告、{result['counts']['info']} 个提示；缺少输入的检查见 skipped"
    return result


def main(argv: list[str] | None = None) -> int:
    from pathlib import Path
    from skill_io import Parser, fail, read_json, schema_errors, write_json
    parser = Parser(description='逐镜头检查真实性；有阻断或格式错误退出 1，读取失败退出 2。')
    parser.add_argument('--facts', type=Path, required=True, help='参数表 JSON')
    parser.add_argument('--shotlist', type=Path, required=True, help='分镜 JSON')
    parser.add_argument('--assets', type=Path, help='素材库 JSON；省略等于空素材库')
    parser.add_argument('--project', type=Path, help='项目元数据 JSON，含 model/render_mode')
    parser.add_argument('--rig', type=Path, help='模型运动配置 JSON')
    parser.add_argument('--mode', choices=['standard', 'photoreal'], help='覆盖项目画面模式')
    parser.add_argument('--out', type=Path, required=True, help='JSON 校验报告路径')
    parser.add_argument('--shotlist-out', type=Path, help='另存含展开台词及计算倍速的分镜；保留人工台词')
    args = parser.parse_args(argv)
    try:
        facts, shotlist = read_json(args.facts), read_json(args.shotlist)
        project = read_json(args.project) if args.project else None
        if args.mode:
            # 模式不意味着模型已提供，保持缺失模型元数据的跳过记录。
            mode_project = {**(project or {}), 'render_mode': args.mode}
        else:
            mode_project = project
        report = validate(facts, shotlist, read_json(args.assets) if args.assets else None,
                          mode_project, read_json(args.rig) if args.rig else None)
        if args.mode and project is None:
            report['skipped'].insert(0, {'codes': ['MODEL_DIMS_MISMATCH', 'MODEL_ASSUMED'], 'reason': '仅指定画面模式，未提供模型元数据，无法核实尺寸或默认值'})
        schema = read_json(Path(__file__).with_name('shotlist.schema.json'))
        report['input_errors'] = schema_errors(shotlist, schema)
        raw_shots = shotlist.get('shots')
        ids = [s.get('id') for s in raw_shots if isinstance(s, dict) and isinstance(s.get('id'), str)] if isinstance(raw_shots, list) else []
        if len(ids) != len(set(ids)):
            report['input_errors'].append({'field': 'shots[].id', 'message': '镜头 id 重复', 'fix': '为每个镜头指定唯一 id，并保留已编辑镜头 id'})
        report['passed'] = report['passed'] and not report['input_errors']
        write_json(args.out, report)
        if args.shotlist_out:
            write_json(args.shotlist_out, shotlist)
        print(report['summary'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return fail(exc)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
