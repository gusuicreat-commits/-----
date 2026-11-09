"""逐项检查分镜；局部坏数据不阻断其余校验。"""
from contextlib import contextmanager
import math
import re
from typing import Any, Iterator

from app import storage
from app.events import emit
from app.model3d.rig import motion_speedup
from .planner import PARAM_DEFAULTS, expected_source
from .text import PLACEHOLDER, find_duplicate_phrases, find_unsourced_numbers, resolve

EQUIPMENT = re.compile(r"起重机|门机|龙门吊|吊车|主梁|支腿|吊钩|小车|crane|gantry|hook|girder", re.I)


def validate(pid: str, run: str) -> dict:
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

    def read(name: str, default: Any) -> Any:
        with check(f"读取 {name}"):
            return storage.read_json(pid, name, default)
        return default

    project = read("project.json", {})
    shotlist = read("shotlist.json", {"shots": [], "analogies": []})
    facts_data = read("facts.json", {"facts": []})
    assets_data = read("assets.json", {"assets": []})
    rig = read("model/rig.json", {"axes": {}})
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
            if kind == "motion":
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
    with check("回写分镜"):
        storage.write_json(pid, "shotlist.json", shotlist)
    with check("校验事件"):
        blocks = sum(i["severity"] == "block" for i in result["issues"])
        warns = sum(i["severity"] == "warn" for i in result["issues"])
        emit(pid, run=run, stage="validate", tool="validate.shotlist", status="warn" if blocks else "ok",
             summary=f"校验 {len(shots)} 个镜头：{blocks} 个阻断、{warns} 个警告")
    with check("保存校验问题"):
        storage.write_json(pid, "issues.json", result)
    return result
