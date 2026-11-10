"""单项目串行、跨项目独立的后台生产流水线。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from uuid import uuid4

from app import events, storage
from app.ingest import facts as ingest
from app.media import blender, compose, tts
from app.model3d import parametric, rig, step
from . import planner, validator, timeline, qa, report
from .text import resolve

STAGES = ("ingest", "model", "plan", "validate", "tts", "render", "compose", "qa", "report")
TOOLS = dict(zip(STAGES, ("pdf.extract", "model.parametric", "llm.opus.plan", "validate.shotlist", "tts.edge",
                          "render.player", "ffmpeg.compose", "llm.opus.visual_qa", "report.provenance")))
_ACTIVE: dict[str, threading.Thread] = {}
_LOCK = threading.RLock()


class RunConflict(Exception):
    """项目已有进行中的运行。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def usable_facts(pid: str) -> list[dict]:
    return [f for f in storage.read_json(pid, "facts.json", {"facts": []})["facts"]
            if f.get("status") in {"verified", "confirmed"}]


def prepare_model(pid: str, run: str, *, step_path: Path | None = None) -> dict:
    directory = storage.project_dir(pid)
    values = {f["id"]: f["value"] for f in usable_facts(pid)}
    kind = "step" if step_path else "parametric"
    tool = "model.step_to_glb" if step_path else "model.parametric"
    with events.tool_call(pid, run, "model", tool, "正在准备三维模型") as call:
        output = directory / "model/crane.glb"
        result = step.import_step(step_path, output) if step_path else parametric.build_parametric(values, output)
        motion = rig.build_rig(values, result["bbox_m"], kind, result["nodes"])
        storage.write_json(pid, "model/rig.json", motion)
        model = {"kind": kind, "glb": "model/crane.glb", "assumed": result.get("assumed", []),
                 "derived_from": list(dict.fromkeys([key for key in result.get("used", {}) if key in values]
                                                   + motion["derived_from"]))}
        if step_path:
            model["step"] = str(step_path.relative_to(directory))
        with events.tool_call(pid, run, "model", "model.dims_check", "正在核验模型尺寸") as dims:
            model["dims_check"] = rig.dims_check(result["bbox_m"], values)
            (dims.warn if any(not item["ok"] for item in model["dims_check"]) else dims.ok)("模型尺寸核验完成")
        with storage.LOCK:
            project = storage.read_json(pid, "project.json")
            project["model"] = model
            storage.write_json(pid, "project.json", project)
        call.ok("模型已生成；引用参数：" + ("、".join(model["derived_from"]) or "无")
                + "；默认值：" + ("、".join(model["assumed"]) or "无"))
    return model


def synthesize_shots(pid: str, run: str) -> None:
    shotlist = storage.read_json(pid, "shotlist.json")
    facts = {f["id"]: f for f in storage.read_json(pid, "facts.json", {"facts": []})["facts"]}
    analogies = timeline.resolve_analogies(shotlist, facts)
    shotlist["analogies"] = list(analogies.values())
    storage.write_json(pid, "shotlist.json", shotlist)

    def synthesize_one(shot: dict) -> None:
        sid = shot["id"]
        output = storage.safe_path(storage.project_dir(pid) / "tts", f"{sid}.mp3")
        try:
            result = tts.synthesize(resolve(shot["narration"], facts, analogies), output)
            events.emit(pid, run=run, stage="tts", tool="tts.edge", status="ok",
                        summary=f"镜头 {sid} 配音完成，时长 {result['duration_s']:.2f} 秒",
                        detail={"shot": sid, "engine": result["engine"], "duration_s": result["duration_s"]})
        except Exception as exc:
            events.emit(pid, run=run, stage="tts", tool="tts.edge", status="error",
                        summary=f"镜头 {sid} 配音失败", detail={"shot": sid, "error": str(exc)})
            raise

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="kepu-tts") as executor:
        list(executor.map(synthesize_one, shotlist["shots"]))


def _execute(pid: str, state: dict, *, from_stage: str | None, force: bool, base_url: str) -> None:
    run = state["run"]
    key = str(storage.project_dir(pid))
    try:
        first = STAGES.index(from_stage) if from_stage else 0
        for stage in STAGES[first:]:
            state["stage"] = stage
            storage.write_json(pid, "run.json", state)
            started = time.monotonic()
            paused = False
            try:
                if stage == "ingest":
                    facts = usable_facts(pid)
                    docs = sorted(path for path in (storage.project_dir(pid) / "docs").iterdir() if path.suffix.lower() == ".pdf")
                    if not facts and docs:
                        for path in docs:
                            ingest.extract_facts(pid, run, path)
                    else:
                        events.emit(pid, run=run, stage=stage, tool="pdf.extract", status="ok",
                                    summary=f"已有 {len(facts)} 条参数，跳过" if facts else "没有 PDF 文档，跳过提取")
                elif stage == "model":
                    model = storage.read_json(pid, "project.json").get("model")
                    if not model:
                        prepare_model(pid, run)
                    else:
                        events.emit(pid, run=run, stage=stage, tool="model.step_to_glb" if model["kind"] == "step" else "model.parametric",
                                    status="ok", summary="已有三维模型，跳过生成")
                elif stage == "plan":
                    if not storage.read_json(pid, "shotlist.json") or from_stage is not None:
                        planner.plan(pid, run)
                    else:
                        events.emit(pid, run=run, stage=stage, tool="llm.opus.plan", status="ok", summary="已有分镜，跳过规划")
                elif stage == "validate":
                    issues = validator.validate(pid, run)
                    if any(i["severity"] == "block" for i in issues["issues"]):
                        planner.repair(pid, run, issues)
                        issues = validator.validate(pid, run)
                    count = sum(i["severity"] == "block" for i in issues["issues"])
                    if count and not force:
                        state["state"] = "paused"
                        events.emit(pid, run=run, stage=stage, tool="validate.shotlist", status="warn",
                                    summary=f"存在 {count} 个阻断问题，等待人工复核")
                        paused = True
                    if count and force:
                        state["forced"] = True
                elif stage == "tts":
                    synthesize_shots(pid, run)
                elif stage == "render":
                    built = timeline.build_timeline(pid)
                    backgrounds = blender.render_model_shots(pid, run, built)
                    for shot in built["shots"]:
                        shot.pop("bg", None)
                        if shot["id"] in backgrounds:
                            shot["bg"] = backgrounds[shot["id"]]
                    storage.write_json(pid, "timeline.json", built)
                    compose.render_video(pid, run, base_url=base_url)
                elif stage == "compose":
                    compose.mux(pid, run)
                elif stage == "qa":
                    try:
                        qa.visual_qa(pid, run, base_url=base_url)
                    except Exception as exc:
                        qa.append_warning(pid, "自动画面质检未完成：" + str(exc)[:500])
                        events.emit(pid, run=run, stage=stage, tool="llm.opus.visual_qa", status="warn",
                                    summary="画面质检失败，请人工复核", detail={"error": str(exc)})
                elif stage == "report":
                    report.build_report(pid)
            finally:
                state["stage_durations_s"][stage] = round(time.monotonic() - started, 4)
                storage.write_json(pid, "run.json", state)
            if paused:
                return
        state["state"] = "done"
    except Exception as exc:
        state.update(state="error", error="流水线执行失败：" + str(exc))
        events.emit(pid, run=run, stage=state["stage"], tool=TOOLS[state["stage"]], status="error",
                    summary="流水线已停止，已完成产物保留，可从失败阶段重跑", detail={"error": str(exc)})
    finally:
        state["finished_at"] = _now()
        storage.write_json(pid, "run.json", state)
        with _LOCK:
            _ACTIVE.pop(key, None)


def start_run(pid: str, *, from_stage: str | None = None, force: bool = False, base_url: str) -> str:
    key = str(storage.project_dir(pid))
    if from_stage is not None and from_stage not in STAGES:
        raise ValueError("未知的流水线阶段")
    with _LOCK:
        if key in _ACTIVE:
            raise RunConflict("该项目正在运行，请等待当前运行结束")
        previous = storage.read_json(pid, "run.json", {})
        # 续跑保留已通过阶段的强制标记，防止报告丢失阻断披露。
        inherited_force = bool(previous.get("forced")) and from_stage in STAGES[4:]
        state = {"run": "r" + uuid4().hex[:12], "state": "running", "stage": from_stage or "ingest",
                 "started_at": _now(), "finished_at": None, "error": None, "forced": force or inherited_force,
                 "stage_durations_s": {}}
        thread = threading.Thread(target=_execute, args=(pid, state),
                                  kwargs={"from_stage": from_stage, "force": force, "base_url": base_url},
                                  daemon=True, name=f"kepu-{pid}")
        storage.write_json(pid, "run.json", state)
        _ACTIVE[key] = thread
        try:
            thread.start()
        except Exception as exc:
            _ACTIVE.pop(key, None)
            state.update(state="error", error="后台运行无法启动：" + str(exc), finished_at=_now())
            storage.write_json(pid, "run.json", state)
            raise
        return state["run"]
