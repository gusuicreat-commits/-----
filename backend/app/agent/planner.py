"""分镜规划与局部改写，类比和来源由程序统一归一。"""
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import llm, storage
from app.events import emit, tool_call
from app.model3d.glbinfo import read_glb_nodes
from .analogy import REFS, compute, preview
from .text import PLACEHOLDER

PARAM_DEFAULTS = {
    "title": {"title": "", "subtitle": ""},
    "outro": {"title": "", "subtitle": ""},
    "model_orbit": {"from_deg": -30, "to_deg": 30, "elevation_deg": 15, "distance": 1.6, "highlight": ["girder"]},
    "analogy": {"analogy": ""},
    "motion": {"axis": "trolley", "from_m": -30, "to_m": 30},
    "exploded": {"parts": ["girder", "leg_left", "leg_right", "trolley"], "spread_m": 12},
    "data_card": {"facts": ["F_rated_load", "F_span"]},
    "real_media": {"asset": "IMG_01", "effect": "kenburns", "caption": ""},
    "ai_broll": {"recipe": "sunrise_port", "palette": "warm", "prompt": ""},
    "weld_macro": {"fact": "F_weld_tolerance", "analogy": ""},
}
KIND_DESCRIPTIONS = '''各 kind 的 params：
  - `title`/`outro`：`{"title":"","subtitle":""}`
  - `model_orbit`：`{"from_deg":-30,"to_deg":30,"elevation_deg":15,"distance":1.6,"highlight":["girder"]}`（distance 为相对包围盒对角线的倍数）
  - `analogy`：`{"analogy":"A_xxx"}` —— 播放器按真实比例并排绘制设备与参照物
  - `motion`：`{"axis":"trolley|hoist|gantry","from_m":-30,"to_m":30}` —— 校验器写入 `speedup`（倍速，≥1），播放器显示「×N 倍速」
  - `exploded`：`{"parts":["girder","leg_left","leg_right","trolley"],"spread_m":12}`
  - `data_card`：`{"facts":["F_rated_load","F_span"]}` —— 每个数值下方显示「来源：文档名 第N页」
  - `real_media`：`{"asset":"IMG_01","effect":"kenburns|none","caption":""}`
  - `ai_broll`：`{"recipe":"sunrise_port|night_factory|blueprint_grid|particles","palette":"warm|cool|steel","prompt":"画面描述"}` —— 不得出现设备本体
  - `weld_macro`：`{"fact":"F_weld_tolerance","analogy":"A_xxx"}`'''
PLANNER_SYSTEM = '''你是工业科普短视频编导，为超大起重机做 {target_s}±10 秒科普片，6–9 个镜头。
叙事：开场钩子 → 有多大（类比）→ 结构 → 怎么动 → 焊缝有多准 → 收尾。
整片镜头安排要求：
- 如素材列表非空，至少安排 1 个 real_media 镜头，params.asset 必须取自素材列表的 id，并列入 asset_refs。
- 必须安排 1 个 data_card 镜头，params.facts 列出 2–4 个最关键参数，只取给定的可引用参数。
- 如有焊缝精度相关参数，必须安排 1 个 weld_macro 镜头讲焊缝精度，params.fact 引用该参数。
- analogy 镜头安排 1–2 个，类比用于最直观的尺寸（长度或高度），焊缝微距不占此数量。
局部改写时以上数量要求针对整片，保留未请求改写的镜头，不为补数量返回额外镜头。
台词里禁止直接写任何数字（阿拉伯数字或中文数字计量）。参数必须用 {{F_id}}，
类比必须用 {{A_<fact去掉F_>_<ref>}} 并在该镜头 analogy_requests 里登记；只能引用给定列表中的 fact。
{{A_x}} 会展开成完整短语（见预览表），台词中不要在它前后重复『相当于』『差不多』『大约』『那么高/长/宽/粗』等词，直接写如『整机高{{F_overall_height}}，{{A_overall_height_building_floor}}！』。
设备结构只能出现在 source=model 的镜头（model_orbit/analogy/motion/exploded/data_card/title/outro/weld_macro）或 real_media。
ai_broll 只用于氛围/转场，params.prompt 描述画面且不得出现起重机、门机、主梁、吊钩等设备词，caption 同样禁止。
provenance=reference 的素材是「参考实拍（非本机）」，配这类画面的台词不能说「这台」「本机」「我们的」，要说「像这样的造船门机」等。
motion 只能用模型 rig 里存在的轴，from_m/to_m 在 range_m 内。
台词口语化、亲切，中文约每秒 4.5 字估算 duration_s（再加 0.8 秒余量）；按占位解析后的字数估算。
每个镜头的 fact_refs 列出台词或画面用到的参数。按 brief 的风格要求。
局部改写保留镜头 id；只返回请求的镜头，仍须遵守全部规则。
''' + KIND_DESCRIPTIONS

PARAM_PROPERTIES: dict[str, dict] = {}
for _defaults in PARAM_DEFAULTS.values():
    for _key, _value in _defaults.items():
        PARAM_PROPERTIES[_key] = ({"type": "array", "items": {"type": "string"}} if isinstance(_value, list)
                                  else {"type": "number"} if isinstance(_value, (int, float)) else {"type": "string"})
REQUEST_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["fact", "ref", "axis"],
                  "properties": {"fact": {"type": "string"}, "ref": {"type": "string", "enum": list(REFS)},
                                 "axis": {"type": "string", "enum": ["length", "height", "mass", "thickness"]}}}
SHOT_SCHEMA = {"type": "object", "additionalProperties": False,
               "required": ["id", "kind", "source", "duration_s", "narration", "fact_refs", "asset_refs", "analogy_requests", "params"],
               "properties": {
                   "id": {"type": "string"}, "kind": {"type": "string", "enum": list(PARAM_DEFAULTS)},
                   "source": {"type": "string", "enum": ["model", "real", "ai", "graphic"]},
                   "duration_s": {"type": "number", "exclusiveMinimum": 0}, "narration": {"type": "string"},
                   "fact_refs": {"type": "array", "items": {"type": "string"}},
                   "asset_refs": {"type": "array", "items": {"type": "string"}},
                   "analogy_requests": {"type": "array", "items": REQUEST_SCHEMA},
                   "params": {"type": "object", "additionalProperties": False, "properties": PARAM_PROPERTIES},
               }}
REPAIR_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["shots"],
                 "properties": {"shots": {"type": "array", "items": SHOT_SCHEMA}}}
PLAN_SCHEMA = deepcopy(REPAIR_SCHEMA)
PLAN_SCHEMA["required"] = ["title", "shots"]
PLAN_SCHEMA["properties"]["title"] = {"type": "string"}


class ShotInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    kind: Literal["title", "outro", "model_orbit", "analogy", "motion", "exploded", "data_card", "real_media", "ai_broll", "weld_macro"]
    source: Literal["model", "real", "ai", "graphic"]
    duration_s: float = Field(gt=0, allow_inf_nan=False)
    narration: str
    fact_refs: list[str]
    asset_refs: list[str]
    analogy_requests: list[dict[str, str]]
    params: dict[str, Any]


def expected_source(kind: str, model: dict | None) -> str:
    if kind == "ai_broll":
        return "ai"
    if kind == "real_media":
        return "real"
    if kind in {"title", "outro", "data_card"} and not model:
        return "graphic"
    return "model"


def _context(pid: str) -> dict:
    project = storage.read_json(pid, "project.json", {})
    model = project.get("model")
    nodes: list[str] = []
    if model and model.get("glb"):
        path = Path(model["glb"])
        if not path.is_absolute():
            path = storage.safe_path(storage.project_dir(pid), str(path))
        nodes = [item["name"] for item in read_glb_nodes(path)]
    facts = storage.read_json(pid, "facts.json", {"facts": []})["facts"]
    assets = storage.read_json(pid, "assets.json", {"assets": []})["assets"]
    return {"brief": project.get("brief", ""),
            "facts": [{**{key: f[key] for key in ("id", "name", "value", "unit")}, "page": f.get("source", {}).get("page")}
                      for f in facts if f.get("status") in {"verified", "confirmed"}],
            "assets": [{key: a.get(key) for key in ("id", "title", "tags", "provenance", "kind")} for a in assets],
            "model": {"kind": model.get("kind"), "rig": storage.read_json(pid, "model/rig.json", {"axes": {}}), "nodes": nodes} if model else None,
            "references": [{"key": key, "name": ref["name"], "axes": ref["axes"]} for key, ref in REFS.items()]}


def _prompt(context: dict, **extra: Any) -> str:
    previews = []
    for fact in context["facts"]:
        if fact.get("status", "verified") not in {"verified", "confirmed"}:
            continue
        unit = fact["unit"]
        label = fact["id"] + fact.get("name", "")
        if unit == "t":
            axis = "mass"
        elif unit in {"m", "mm"}:
            axis = ("thickness" if any(word in label for word in ("thickness", "tolerance", "厚", "错边", "焊缝"))
                    else "height" if "height" in label or "高" in label else "length")
        else:
            continue
        for ref, item in REFS.items():
            if axis in item["axes"]:
                aid = f"A_{fact['id'].removeprefix('F_')}_{ref}"
                previews.append("{{" + aid + "}} → " + preview(fact, ref, axis))
    return json.dumps({**context, **extra, "类比展开预览": previews}, ensure_ascii=False, sort_keys=True)


def _normalise(raw: dict, sid: str, model: dict | None, facts: dict[str, dict], notes: list[str]) -> tuple[dict, list[dict]]:
    try:
        shot = ShotInput.model_validate(raw).model_dump()
    except ValidationError as exc:
        raise llm.LLMError("分镜返回格式无效") from exc
    shot["id"] = sid
    shot["source"] = expected_source(shot["kind"], model)
    defaults = deepcopy(PARAM_DEFAULTS[shot["kind"]])
    shot["params"] = {key: shot["params"].get(key, value) for key, value in defaults.items()}
    calculated = []
    for request in shot.pop("analogy_requests"):
        try:
            fid, ref = request["fact"], request["ref"]
            aid = f"A_{fid.removeprefix('F_')}_{ref}"
            calculated.append(compute(aid, facts[fid], ref, request["axis"]))
            if fid not in shot["fact_refs"]:
                shot["fact_refs"].append(fid)
        except (KeyError, ValueError, TypeError) as exc:
            notes.append(f"镜头 {sid} 的类比请求已丢弃：参数、参照物或方向无效（{exc}）")
    if calculated and shot["kind"] in {"analogy", "weld_macro"}:
        shot["params"]["analogy"] = calculated[0]["id"]
    refs = [key for key in PLACEHOLDER.findall(shot["narration"]) if key.startswith("A_")]
    refs += [a["id"] for a in calculated]
    if shot["params"].get("analogy"):
        refs.append(shot["params"]["analogy"])
    shot["analogy_refs"] = list(dict.fromkeys(refs))
    shot["review"] = {"status": "pending", "note": ""}
    return shot, calculated


def _save(pid: str, run: str, result: dict, calculated: list[dict]) -> dict:
    used = {aid for s in result["shots"] for aid in s.get("analogy_refs", [])}
    used.update(s.get("params", {}).get("analogy") for s in result["shots"])
    by_id = {a["id"]: a for a in result.get("analogies", [])}
    by_id.update({a["id"]: a for a in calculated})
    result["analogies"] = [a for aid, a in by_id.items() if aid in used]
    storage.write_json(pid, "shotlist.json", result)
    unique = {a["id"]: a for a in calculated}
    emit(pid, run=run, stage="plan", tool="analogy.compute", status="ok",
         summary=f"计算 {len(unique)} 个类比：" + "；".join(a["text"] for a in unique.values()))
    return result


def plan(pid: str, run: str, *, target_s: float = 45) -> dict:
    context = _context(pid)
    with tool_call(pid, run, "plan", "llm.opus.plan", "正在依据资料生成分镜") as call:
        raw = llm.complete_json("plan", PLANNER_SYSTEM.replace("{target_s}", f"{target_s:g}"),
                                _prompt(context), PLAN_SCHEMA, pid=pid)
        if not isinstance(raw.get("title"), str) or not isinstance(raw.get("shots"), list) or not raw["shots"]:
            raise llm.LLMError("分镜返回格式无效")
        result = {"version": 1, "title": raw["title"], "fps": 30, "width": 1920, "height": 1080,
                  "shots": [], "analogies": [], "notes": []}
        facts = {f["id"]: f for f in context["facts"]}
        calculated = []
        for index, item in enumerate(raw["shots"], 1):
            shot, analogies = _normalise(item, f"S{index}", context["model"], facts, result["notes"])
            result["shots"].append(shot)
            calculated.extend(analogies)
        _save(pid, run, result, calculated)
        duration = sum(s["duration_s"] for s in result["shots"])
        call.ok(f"生成 {len(result['shots'])} 个镜头，预计 {duration:g} 秒")
    return result


def _edit(pid: str, run: str, selected: list[str], issues: list[dict], instruction: str, task: str) -> dict:
    context = _context(pid)
    result = storage.read_json(pid, "shotlist.json")
    shots = [s for s in result["shots"] if s["id"] in selected]
    if len(shots) != len(selected):
        raise KeyError("待改写镜头不存在")
    if not shots:
        return result
    with tool_call(pid, run, "plan", f"llm.opus.{task}", "正在依据问题和指令改写分镜") as call:
        extra = {"issues": issues, "instruction": instruction, "analogies": result.get("analogies", [])}
        extra["shot" if task == "revise" else "shots"] = shots[0] if task == "revise" else shots
        duration = sum(s["duration_s"] for s in result["shots"])
        raw = llm.complete_json(task, PLANNER_SYSTEM.replace("{target_s}", f"{duration:g}"), _prompt(context, **extra),
                                SHOT_SCHEMA if task == "revise" else REPAIR_SCHEMA, pid=pid)
        replacements = [raw] if task == "revise" else raw.get("shots", [])
        if task == "revise":
            replacements[0] = {**replacements[0], "id": selected[0]}
        ids = [s.get("id") for s in replacements]
        if len(ids) != len(selected) or set(ids) != set(selected):
            raise llm.LLMError("改写结果必须恰好包含指定镜头，不能遗漏或新增")
        facts = {f["id"]: f for f in context["facts"]}
        revised, calculated = {}, []
        result.setdefault("notes", [])
        for item in replacements:
            shot, analogies = _normalise(item, item["id"], context["model"], facts, result["notes"])
            revised[shot["id"]] = shot
            calculated.extend(analogies)
        result["shots"] = [revised.get(s["id"], s) for s in result["shots"]]
        # 重算仍使用的旧类比，避免人工修改参数后继续使用旧比例。
        for old in result.get("analogies", []):
            if old["id"] not in {a["id"] for a in calculated}:
                try:
                    calculated.append(compute(old["id"], facts[old["fact"]], old["ref"], old["axis"]))
                except (KeyError, ValueError, TypeError):
                    result["notes"].append(f"类比 {old['id']} 已失效，请重新选择可引用参数")
        result["analogies"] = []
        _save(pid, run, result, calculated)
        call.ok(f"已改写 {len(revised)} 个镜头，待人工复核")
    return result


def revise_shot(pid: str, run: str, sid: str, instruction: str) -> dict:
    from .validator import validate
    issues = validate(pid, run)["issues"]
    return _edit(pid, run, [sid], [i for i in issues if i.get("shot") == sid], instruction, "revise")


def repair(pid: str, run: str, issues: dict | list[dict]) -> dict:
    entries = issues["issues"] if isinstance(issues, dict) else issues
    blocks = [i for i in entries if i.get("severity") == "block" and i.get("shot")]
    selected = list(dict.fromkeys(i["shot"] for i in blocks))
    return _edit(pid, run, selected, blocks, "修正所有阻断问题，保留原有叙事意图。", "repair")
