"""分镜规划与局部改写，类比和来源由程序统一归一。"""
from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import config, llm, storage
from app.events import emit, tool_call
from app.model3d.glbinfo import read_glb_nodes
from .analogy import REFS, compute, preview
from .director import select_recipe
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
台词、字幕和标题不得夸大：最高级须同句引用 verified 且 claim_type=ranking 的对应排名事实（EXAGGERATION）；避免绝对承诺（ABSOLUTE_CLAIM），改用精度参数；同名或同 key 的 verified 参数数值冲突不得选择或引用，交人工确认（FACT_CONFLICT）；名称与单位量纲不符须核实（UNIT_SUSPECT）。
台词口语化、亲切，中文约每秒 4.5 字估算 duration_s（再加 0.8 秒余量）；按占位解析后的字数估算。
每个镜头的 fact_refs 列出台词或画面用到的参数。按 brief 的风格要求。
每句台词必须登记 claims，text 为原句，support 为 fact_id、asset_id 或 generic；具体型号、客户、地名、年份、认证、排名和设备用途/结构不能用 generic，用带出处的 qualitative 事实支撑。
局部改写保留镜头 id；只返回请求的镜头，仍须遵守全部规则。
''' + KIND_DESCRIPTIONS

PHOTOREAL_SYSTEM = "画面风格为写实三维：模型镜头是本片最强画面。开场第一个镜头用 model_orbit（整机环绕，highlight 选 girder），若有 real_media 放在第二个；必须各有 1 个 exploded 与 motion；model_orbit、exploded、motion、title 合计不少于 3 个；analogy 最多 1 个。"


def planner_system(pid: str, target_s: float) -> str:
    system = PLANNER_SYSTEM.replace("{target_s}", f"{target_s:g}")
    project = storage.read_json(pid, "project.json", {})
    directed = project.get("director_recipe", "off") != "off"
    if target_s <= 20 or directed:
        # Keep evidence/claims rules intact; replace the full-film quantity mandates.
        system = system[system.index("台词里禁止"):]
        budget = "3–4" if target_s <= 20 else "3–9"
        system = (f"你是工业科普短视频编导，目标 {target_s:g} 秒（总时长误差不超过 1 秒），{budget} 个镜头。"
                  "聚焦一个观众问题，不塞完整长片的全部主题。每镜一个信息点，按展开台词核对时长。"
                  "如上下文含 director，只执行选中的 sequence 与证据约束；data_card 可只放一个核心参数。"
                  "缺证据时说明缺项，不编造或悄悄省略用户必讲内容。局部改写只返回指定镜头。\n" + system)
    if project.get("production_engine") and target_s >= 30 and project.get("render_mode") != "scale_film":
        system = (f"你是工业科普短视频编导，目标 {target_s:g} 秒（总时长误差不超过 1 秒），6–9 个镜头。"
                  "选中的 director 是讲解主题和证据约束，不是固定三镜模板；不要把三镜拉长充数。"
                  "每个新增机位应建立新的空间信息或完成收束，允许少台词的视觉建立镜，不重复同一数字。"
                  "遵循上下文 cinematography 的景别节奏与轴线连贯指导。尺度主题无需添加设备运动或结构拆解。"
                  "model_orbit 只能使用已有 from_deg/to_deg/elevation_deg/distance/highlight，"
                  "通过这些参数改变观察角度和距离；相机绕行不等于设备运动。"
                  "未实现的横移轨迹、局部look-at、转场path不得假装自动执行，不新增schema外params。"
                  "按 render_capabilities 选择两端真实支持的镜头和类比；精细制作禁止weld_macro，"
                  "精细类比只支持building_floor/football_field，缺证据仍须停止。局部修改只返回指定镜头。\n"
                  + PLANNER_SYSTEM[PLANNER_SYSTEM.index("台词里禁止"):])
    if project.get("production_engine"):
        system += ("\n围绕观众问题连续叙事，台词承接上文并引出下一层理解，避免每镜都用换个角度、看整体等报幕句；允许必要的视觉留白，不要求固定段数。遵循上下文copywriting指导。台词按事实和观察分句，每句单独登记claims。含{{F_x}}的数值事实句用对应F_id支持；"
                   "含{{A_x}}的类比句用其底层F_id支持；不要把数值事实与额外工程结论写成一句再共用证据。"
                   "机位观察只说画面可见的方位和延展，不从示意模型推断真实设备的结构类型、材质或受力性能。"
                   "尺度片避免双梁、箱形、箱梁、承重框架等缺少qualitative事实且可能与示意几何不一致的结构断言；"
                   "不能靠改成generic或删除claims规避校验，缺依据就删除该断言并保留有据尺度讲解。")
    if project.get("render_mode") == "photoreal":
        system += "\n" + PHOTOREAL_SYSTEM
    return system


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
                   "claims": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                              "required": ["text", "support"], "properties": {
                                  "text": {"type": "string"}, "support": {"type": "string"}}}},
                   "asset_refs": {"type": "array", "items": {"type": "string"}},
                   "analogy_requests": {"type": "array", "items": REQUEST_SCHEMA},
                   "params": {"type": "object", "additionalProperties": False, "properties": PARAM_PROPERTIES},
               }}
REPAIR_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["shots"],
                 "properties": {"shots": {"type": "array", "items": SHOT_SCHEMA}}}
PLAN_SCHEMA = deepcopy(REPAIR_SCHEMA)
PLAN_SCHEMA["required"] = ["title", "shots"]
PLAN_SCHEMA["properties"]["title"] = {"type": "string"}


class ClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1)
    support: str = Field(min_length=1)


class ShotInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    kind: Literal["title", "outro", "model_orbit", "analogy", "motion", "exploded", "data_card", "real_media", "ai_broll", "weld_macro"]
    source: Literal["model", "real", "ai", "graphic"]
    duration_s: float = Field(gt=0, allow_inf_nan=False)
    narration: str
    claims: list[ClaimInput] | None = None
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


def _context(pid: str, target_s: float | None = None) -> dict:
    project = storage.read_json(pid, "project.json", {})
    if target_s is None:
        target_s = project.get("target_s", 45)
    model = project.get("model")
    nodes: list[str] = []
    if model and model.get("glb"):
        path = Path(model["glb"])
        if not path.is_absolute():
            path = storage.safe_path(storage.project_dir(pid), str(path))
        nodes = [item["name"] for item in read_glb_nodes(path)]
    facts = storage.read_json(pid, "facts.json", {"facts": []})["facts"]
    assets = storage.read_json(pid, "assets.json", {"assets": []})["assets"]
    context = {"brief": project.get("brief", ""),
            "facts": [{**{key: f[key] for key in ("id", "name", "value", "unit")}, "page": f.get("source", {}).get("page"),
                       "status": f["status"], "source": f.get("source", {}),
                       **{key: f[key] for key in ("claim_type", "key", "type") if key in f}}
                      for f in facts if f.get("status") in {"verified", "confirmed"}],
            "assets": [{key: a.get(key) for key in ("id", "title", "tags", "provenance", "kind")} for a in assets],
            "model": {"kind": model.get("kind"), "rig": storage.read_json(pid, "model/rig.json", {"axes": {}}), "nodes": nodes} if model else None,
            "references": [{"key": key, "name": ref["name"], "axes": ref["axes"]} for key, ref in REFS.items()]}
    if project.get("production_engine"):
        context["copywriting"] = (config.ROOT / "skills/industrial-explainer-storyboard/references/copywriting.md").read_text(encoding="utf-8")
    requested = project.get("director_recipe", "off")
    if requested != "off":
        context["director"] = select_recipe(context, requested, target_s)
    if project.get("production_engine") and target_s >= 30 and project.get("render_mode") != "scale_film":
        director = context.get("director", {})
        director["planning_mode"] = "expanded_theme"
        director["shot_budget"] = [6, 9]
        director["theme_evidence"] = [{k: shot[k] for k in ("kind", "params", "fact_refs", "analogy_requests") if k in shot}
                                      for shot in director.pop("sequence", [])]
        context["director"] = director
        guidance = config.ROOT / "skills/industrial-explainer-storyboard/references/cinematography.md"
        context["cinematography"] = guidance.read_text(encoding="utf-8").split("## 本轮可选例")[0]
        engine = project["production_engine"]
        context["render_capabilities"] = {"engine": engine,
            "shot_kinds": [kind for kind in PARAM_DEFAULTS if engine != "blender" or kind != "weld_macro"],
            "supported_analogy_refs": ["building_floor", "football_field"] if engine == "blender" else list(REFS),
            "camera_params": ["from_deg", "to_deg", "elevation_deg", "distance", "highlight"],
            "unsupported": ["T26 custom paths", "custom look-at", "custom transition paths"]}
    return context


def _prompt(context: dict, **extra: Any) -> str:
    previews = []
    for fact in context["facts"]:
        if fact.get("status", "verified") not in {"verified", "confirmed"}:
            continue
        if fact.get("type") == "qualitative":
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
    if shot["claims"] is None:
        shot.pop("claims")
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


def plan(pid: str, run: str, *, target_s: float | None = None) -> dict:
    if storage.read_json(pid, "project.json", {}).get("render_mode") == "scale_film":
        from .scale_film import compile_plan
        return compile_plan(pid, run)
    if target_s is None:
        target_s = storage.read_json(pid, "project.json", {}).get("target_s", 45)
    context = _context(pid, target_s)
    if storage.read_json(pid, "project.json", {}).get("production_engine"):
        storage.write_json(pid, "director-plan.json", context.get("director", {}))
    previous = storage.read_json(pid, "shotlist.json", {})
    locked = {s["id"]: s for s in previous.get("shots", [])
              if s.get("human_edited") or s.get("review", {}).get("status") == "approved"}
    if locked:
        reserved = sum(s["duration_s"] for s in locked.values())
        if reserved >= target_s or (target_s <= 20 and len(locked) > 4):
            raise ValueError("人工确认镜头已占满或超出目标预算；请明确调整这些镜头后再规划")
        context["preserved_shots"] = list(locked.values())
        context["remaining_duration_s"] = target_s - reserved
        context["preservation_instruction"] = "返回完整分镜并包含所有 preserved_shots 的原 id；这些镜头的全部字段由程序保留，只分配剩余时长给其他镜头。预算不足须停止，不改人工字段。"
    if context.get("director", {}).get("status") == "needs_evidence":
        raise ValueError("讲解配方缺证据：" + json.dumps(context["director"]["unavailable"], ensure_ascii=False))
    with tool_call(pid, run, "plan", "llm.opus.plan", "正在依据资料生成分镜") as call:
        raw = llm.complete_json("plan", planner_system(pid, target_s),
                                _prompt(context), PLAN_SCHEMA, pid=pid)
        if not isinstance(raw.get("title"), str) or not isinstance(raw.get("shots"), list) or not raw["shots"]:
            raise llm.LLMError("分镜返回格式无效")
        if locked:
            ids = [item.get("id") for item in raw["shots"]]
            if len(set(ids)) != len(ids) or not set(locked) <= set(ids):
                raise llm.LLMError("重规划必须包含全部人工确认镜头原 id，且不能重复")
            raw["shots"] = [deepcopy(locked.get(item["id"], item)) for item in raw["shots"]]
        if target_s <= 20 or "director" in context or locked:
            maximum = 4 if target_s <= 20 else 9
            minimum = 6 if context.get("director", {}).get("planning_mode") == "expanded_theme" else 3
            if not minimum <= len(raw["shots"]) <= maximum:
                raise llm.LLMError("分镜超出讲解配方镜头预算，需重新规划")
            try:
                duration = sum(float(s["duration_s"]) for s in raw["shots"])
            except (KeyError, TypeError, ValueError) as exc:
                raise llm.LLMError("分镜返回时长无效") from exc
            if not math.isfinite(duration) or abs(duration - target_s) > 1:
                raise llm.LLMError("分镜总时长超出目标一秒容差，需重新规划")
        result = {"version": 1, "title": raw["title"], "fps": 30, "width": 1920, "height": 1080,
                  "shots": [], "analogies": deepcopy(previous.get("analogies", [])) if locked else [], "notes": []}
        facts = {f["id"]: f for f in context["facts"]}
        calculated = []
        for index, item in enumerate(raw["shots"], 1):
            if locked and item["id"] in locked:
                shot, analogies = deepcopy(locked[item["id"]]), []
            else:
                sid = item["id"] if locked else f"S{index}"
                shot, analogies = _normalise(item, sid, context["model"], facts, result["notes"])
            result["shots"].append(shot)
            calculated.extend(analogies)
        _save(pid, run, result, calculated)
        duration = sum(s["duration_s"] for s in result["shots"])
        call.ok(f"生成 {len(result['shots'])} 个镜头，预计 {duration:g} 秒")
    return result


def _edit(pid: str, run: str, selected: list[str], issues: list[dict], instruction: str, task: str) -> dict:
    result = storage.read_json(pid, "shotlist.json")
    duration = sum(s["duration_s"] for s in result["shots"])
    context = _context(pid, duration)
    shots = [s for s in result["shots"] if s["id"] in selected]
    if len(shots) != len(selected):
        raise KeyError("待改写镜头不存在")
    if task == "repair":
        # Explicit user revise remains authorized; automatic repairs cannot rewrite approvals.
        locked = {s["id"] for s in shots if s.get("human_edited") or s.get("review", {}).get("status") == "approved"}
        selected = [sid for sid in selected if sid not in locked]
        shots = [s for s in shots if s["id"] not in locked]
        if locked:
            emit(pid, run=run, stage="plan", tool="director.preserve", status="warn",
                 summary="自动修复保留人工确认镜头 " + "/".join(sorted(locked)) + "，其问题仍需人工处理")
    if not shots:
        return result
    with tool_call(pid, run, "plan", f"llm.opus.{task}", "正在依据问题和指令改写分镜") as call:
        extra = {"issues": issues, "instruction": instruction, "analogies": result.get("analogies", [])}
        extra["shot" if task == "revise" else "shots"] = shots[0] if task == "revise" else shots
        duration = sum(s["duration_s"] for s in result["shots"])
        raw = llm.complete_json(task, planner_system(pid, duration), _prompt(context, **extra),
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
            if storage.read_json(pid, "project.json", {}).get("production_engine"):
                if task == "revise":
                    shot["human_edited"] = True
                elif task == "repair":
                    shot["duration_s"] = next(old["duration_s"] for old in shots if old["id"] == shot["id"])
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
    instruction = "修正所有阻断问题，保留原有叙事意图。"
    if storage.read_json(pid, "project.json", {}).get("production_engine"):
        instruction = ("修正所有阻断问题，保留原有叙事意图、镜头ID与时长。按事实和观察分句，每句单独登记claims，"
                       "事实句使用对应F_id支持；删除无依据结构断言，不以generic或省略claims规避校验。"
                       "尺度片不添加双梁箱形等超出示意几何和事实的工程结论。")
    return _edit(pid, run, selected, blocks, instruction, "repair")
