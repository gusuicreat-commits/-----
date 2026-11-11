"""Reviewed-plan workflow: silent previews and explicit, revision-bound production."""
from contextlib import contextmanager
from functools import wraps, lru_cache
import hashlib
import json
from pathlib import Path
import threading
from uuid import uuid4
import zipfile

from app import config, events, storage, llm
from app.media import blender, compose
from . import orchestrator, planner, timeline, validator, report, qa


def capabilities():
    available = blender.blender_executable() is not None
    common = list(planner.PARAM_DEFAULTS)
    return {"provider": llm.provider_status() if hasattr(llm, "provider_status") else {"configured": False, "error": "模型适配未就绪"}, "engines": [{"id": "threejs", "available": True, "label": "轻量快制", "shot_kinds": common},
                        {"id": "blender", "available": available, "label": "精细制作",
                         "shot_kinds": [k for k in common if k != "weld_macro"],
                         "supported_analogy_refs": sorted(blender.ANALOGY_REFS),
                         "note": "构图预览使用 Three.js；精细关键帧逐镜真实生成。精细制作仅支持参数化模型和楼层/足球场类比；实拍、信息图由网页合成。"}],
            "contents": ["auto", "scale", "motion", "structure"], "preview_has_audio": False}


@lru_cache(maxsize=512)
def _file_digest(path: str, size: int, mtime_ns: int, ctime_ns: int, inode: int) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_digest(path: Path) -> str:
    stat = path.stat()
    return _file_digest(str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)


def _seal_exports(pid, run, revision, exports):
    root = storage.project_dir(pid)
    files = {}
    for key, url in exports.items():
        prefix = f"/files/{pid}/"
        if not url.startswith(prefix):
            raise ValueError("导出路径与当前项目不匹配")
        relative = url[len(prefix):]
        path = storage.safe_path(root, relative)
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError("本次制作缺少有效导出文件：" + relative)
        files[key] = {"path": relative, "sha256": file_digest(path), "size": path.stat().st_size}
    storage.write_json(pid, "deliverables.json", {"run": run, "plan_revision": revision, "files": files})


def _exports_current(pid, state):
    manifest = storage.read_json(pid, "deliverables.json", {})
    if manifest.get("run") != state.get("run") or manifest.get("plan_revision") != state.get("plan_revision"):
        return False
    try:
        return bool(manifest.get("files")) and all(
            (path := storage.safe_path(storage.project_dir(pid), item["path"])).is_file()
            and path.stat().st_size == item["size"] and file_digest(path) == item["sha256"]
            for item in manifest["files"].values())
    except (OSError, ValueError, KeyError):
        return False


def _model_input_signature(pid):
    values = {fact["id"]: fact["value"] for fact in orchestrator.usable_facts(pid)}
    payload = {"values": values, "builder": {
        name: file_digest(config.ROOT / "backend/app/model3d" / name)
        for name in ("parametric.py", "rig.py")}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _model_current(pid):
    model = storage.read_json(pid, "project.json").get("model")
    if not model:
        return False
    if model.get("kind") != "parametric":
        return True
    try:
        root = storage.project_dir(pid)
        glb = storage.safe_path(root, model["glb"])
        rig = root / "model/rig.json"
        return (model.get("workflow_input_signature") == _model_input_signature(pid)
                and model.get("workflow_glb_sha256") == file_digest(glb)
                and model.get("workflow_rig_sha256") == file_digest(rig))
    except (KeyError, OSError, ValueError):
        return False


def _ensure_model_current(pid, run):
    if _model_current(pid):
        return
    # Missing provenance is not evidence that an old GLB matches current facts.
    signature = _model_input_signature(pid)
    model = orchestrator.prepare_model(pid, run)
    if _model_input_signature(pid) != signature:
        raise ValueError("模型生成期间参数发生变化，请重新预览")
    root = storage.project_dir(pid)
    model.update(workflow_input_signature=signature,
                 workflow_glb_sha256=file_digest(storage.safe_path(root, model["glb"])),
                 workflow_rig_sha256=file_digest(root / "model/rig.json"))
    project = storage.read_json(pid, "project.json")
    project["model"] = model
    storage.write_json(pid, "project.json", project)


def _recover_interrupted(pid):
    with orchestrator._LOCK:
        state = storage.read_json(pid, "workflow.json", {"state": "idle"})
        if state.get("state") in {"previewing", "producing"} and str(storage.project_dir(pid)) not in orchestrator._ACTIVE:
            state.update(state="error", exports={}, interrupted=True,
                         error="上次后台任务已中断，请重新预览当前方案后再制作")
            storage.write_json(pid, "workflow.json", state)
            previous_run = storage.read_json(pid, "run.json", {})
            if previous_run.get("run") and previous_run.get("run") == state.get("run"):
                storage.write_json(pid, "run.json", {**previous_run, "state": "error", "error": state["error"]})
        return state


def _repair_generated(pid, run, state, issues):
    for attempt in range(2):
        shots = storage.read_json(pid, "shotlist.json", {}).get("shots", [])
        eligible = {shot["id"] for shot in shots if not shot.get("human_edited")
                    and shot.get("review", {}).get("status") != "approved"}
        selected = [issue for issue in issues if issue.get("severity") == "block" and issue.get("shot") in eligible]
        if not selected:
            break
        state["repair_attempts"] = attempt + 1
        events.emit(pid, run=run, stage="plan", tool="workflow.repair", status="start",
                    summary=f"正在自动修复生成方案的阻断问题（第 {attempt + 1}/2 轮）")
        planner.repair(pid, run, selected)
        issues = _validated(pid, run)
    return issues


def fingerprint(pid):
    project = storage.read_json(pid, "project.json")
    payload = {"project": {k: project.get(k) for k in ("brief", "target_s", "production_engine", "director_recipe", "render_mode", "model")},
               **{name: storage.read_json(pid, name, {}) for name in ("facts.json", "assets.json", "shotlist.json", "model/rig.json")}}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
    root = storage.project_dir(pid)
    for folder in ("docs", "assets", "model"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(root)).encode())
                digest.update(file_digest(path).encode())
    return digest.hexdigest()


def status(pid):
    state = _recover_interrupted(pid)
    current = bool(state.get("plan_revision")) and state["plan_revision"] == fingerprint(pid)
    project = storage.read_json(pid, "project.json")
    provider = capabilities()["provider"]
    state = {**state, "current": current, "brief": project.get("brief", ""), "target_s": project.get("target_s", 30),
             "engine": project.get("production_engine", "threejs"), "content": project.get("director_recipe", "auto"),
             "director_plan": storage.read_json(pid, "director-plan.json", {}),
             "provider": provider, "can_preview": bool(provider.get("configured")) and state["state"] not in {"previewing", "producing"}}
    if state["state"] in {"preview_ready", "production_done", "blocked"} and not current:
        state["state"] = "stale"
    if state["state"] == "preview_ready" and not _model_current(pid):
        current = False
        state["current"] = False
        state.update(state="stale", error="参数或模型已变化，请重新预览以重建模型和尺寸核验")
    state["can_produce"] = current and state["state"] == "preview_ready"
    state["can_download"] = current and state["state"] == "production_done" and _exports_current(pid, state)
    if current and state["state"] == "production_done" and not state["can_download"]:
        state.update(state="stale", error="导出文件缺失或内容与本次制作不匹配，请重新预览制作")
    if not state["can_download"]:
        state["exports"] = {}
    if not current:
        state["preview"] = None
    return state


@contextmanager
def editing(pid):
    with orchestrator._LOCK:
        if str(storage.project_dir(pid)) in orchestrator._ACTIVE:
            raise orchestrator.RunConflict("该项目正在运行，请等待完成后修改")
        yield


def project_mutation(fn):
    @wraps(fn)
    def wrapped(pid, *args, **kwargs):
        with editing(pid):
            return fn(pid, *args, **kwargs)
    return wrapped


def brief(pid, changes):
    with editing(pid):
        project = storage.read_json(pid, "project.json")
        project.update(brief=changes["brief"], target_s=changes["target_s"],
                       production_engine=changes["engine"], director_recipe=changes["content"], render_mode="standard")
        storage.write_json(pid, "project.json", project)
        if storage.read_json(pid, "workflow.json") is None:
            storage.write_json(pid, "workflow.json", {"state": "idle", "exports": {}})
    return status(pid)


def engine_issues(pid):
    project = storage.read_json(pid, "project.json")
    if project.get("production_engine", "threejs") != "blender":
        return []
    messages = []
    if not blender.blender_executable():
        messages.append("未找到 Blender，无法精细制作；请安装引擎或明确选择轻量快制")
    if (project.get("model") or {}).get("kind") == "step":
        messages.append("当前精细引擎尚不能忠实渲染导入 STEP，请选择轻量快制或使用参数化示意模型")
    shots = storage.read_json(pid, "shotlist.json", {})
    analogies = {a["id"]: a for a in shots.get("analogies", [])}
    for shot in shots.get("shots", []):
        if shot["kind"] == "weld_macro":
            messages.append(f"{shot['id']} 焊缝微距尚不支持精细制作")
        if shot["kind"] == "analogy" and analogies.get(shot.get("params", {}).get("analogy"), {}).get("ref") not in blender.ANALOGY_REFS:
            messages.append(f"{shot['id']} 类比参照物尚不支持精细制作")
    return [{"id": f"ENGINE_{i}", "severity": "block", "shot": None, "message": m, "hint": "修改方案或选择支持的引擎"} for i, m in enumerate(messages)]


def _validated(pid, run):
    result = validator.validate(pid, run)
    result["issues"].extend(engine_issues(pid))
    storage.write_json(pid, "issues.json", result)
    return result["issues"]


def _production(pid, run, base_url, revision):
    if fingerprint(pid) != revision:
        raise ValueError("方案已改变，请重新预览")
    if not _model_current(pid):
        raise ValueError("参数化模型与当前参数不匹配，请重新预览重建模型")
    issues = _validated(pid, run)
    if any(i["severity"] == "block" for i in issues):
        raise ValueError("当前方案存在阻断问题，不能制作")
    if fingerprint(pid) != revision:
        raise ValueError("校验更新了方案，请重新预览确认")
    root = storage.project_dir(pid)
    previous_final = (root / "renders/final.mp4").stat() if (root / "renders/final.mp4").is_file() else None
    storage.write_json(pid, "run.json", {"run": run, "state": "running", "stage": "tts", "forced": False, "stage_durations_s": {}})
    orchestrator.synthesize_shots(pid, run)
    built = timeline.build_timeline(pid)
    backgrounds = blender.render_model_shots(pid, run, built)
    for shot in built["shots"]:
        shot.pop("bg", None)
        if shot["id"] in backgrounds:
            shot["bg"] = backgrounds[shot["id"]]
    if storage.read_json(pid, "project.json").get("production_engine") == "blender":
        built["render_mode"] = "photoreal"
    storage.write_json(pid, "timeline.json", built)
    compose.render_video(pid, run, base_url=base_url)
    compose.mux(pid, run)
    produced = root / "renders/final.mp4"
    if not produced.is_file() or produced.stat().st_size <= 0:
        raise ValueError("本次制作未生成有效 MP4")
    actual = produced.stat()
    if previous_final and (actual.st_mtime_ns, actual.st_ctime_ns, actual.st_size, actual.st_ino) == (previous_final.st_mtime_ns, previous_final.st_ctime_ns, previous_final.st_size, previous_final.st_ino):
        raise ValueError("本次制作没有更新 MP4，拒绝沿用旧成片")
    try:
        qa.visual_qa(pid, run, base_url=base_url)
    except Exception as exc:
        qa.append_warning(pid, "自动画面质检未完成：" + str(exc)[:500])
    report.build_report(pid)
    # Derived analogy records may be refreshed by TTS; source plan must stay identical.
    if fingerprint(pid) != revision:
        raise ValueError("制作期间方案发生变化，成片不予发布，请重新预览")
    root = storage.project_dir(pid)
    if not (root / "renders/final.mp4").is_file():
        raise ValueError("制作未生成 MP4")
    with zipfile.ZipFile(root / "project.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("project.json", "facts.json", "assets.json", "shotlist.json", "timeline.json", "report.json", "report.html"):
            if (root / name).is_file():
                archive.write(root / name, name)
        for folder in ("docs", "assets", "model"):
            for path in (root / folder).rglob("*"):
                if path.is_file():
                    archive.write(path, str(path.relative_to(root)))
    return {"mp4": f"/files/{pid}/renders/final.mp4", "project": f"/files/{pid}/project.zip",
            "sources": f"/files/{pid}/report.html", "report": f"/files/{pid}/report.json"}


def _worker(pid, state, replan, base_url):
    production = state["state"] == "producing"
    run = state["run"]
    try:
        if production:
            state["exports"] = _production(pid, run, base_url, state["plan_revision"])
            _seal_exports(pid, run, state["plan_revision"], state["exports"])
            state["state"] = "production_done"
            storage.write_json(pid, "run.json", {**storage.read_json(pid, "run.json", {}), "state": "done", "stage": "report"})
        else:
            if replan and not orchestrator.usable_facts(pid):
                for document in sorted((storage.project_dir(pid) / "docs").glob("*.pdf")):
                    orchestrator.ingest.extract_facts(pid, run, document)
            _ensure_model_current(pid, run)
            if replan:
                planner.plan(pid, run)
            issues = _validated(pid, run)
            if replan:
                issues = _repair_generated(pid, run, state, issues)
            state["issues"] = issues
            state["plan_revision"] = fingerprint(pid)
            preview = timeline.build_preview(pid)
            preview["plan_revision"] = state["plan_revision"]
            storage.write_json(pid, "preview-timeline.json", preview)
            state["preview"] = {"timeline_url": f"/files/{pid}/preview-timeline.json", "engine": "threejs",
                                "keyframes_status": "pending" if storage.read_json(pid, "project.json").get("production_engine") == "blender" else "realtime"}
            blocked = any(i["severity"] == "block" for i in issues)
            if storage.read_json(pid, "project.json").get("production_engine") == "blender" and not blocked:
                state["preview"]["keyframes_status"] = "rendering"
                storage.write_json(pid, "workflow.json", state)
                state["preview"]["keyframes"] = blender.preview_keyframes(pid, run, preview, state["plan_revision"])
                state["preview"]["keyframes_status"] = "ready"
            state["state"] = "blocked" if blocked else "preview_ready"
        events.emit(pid, run=run, stage="workflow", tool="workflow", status="ok", summary="制作完成" if production else "分镜预览已生成", detail={"state": state["state"]})
    except Exception as exc:
        state.update(state="error", error=str(exc), exports={})
        if production:
            storage.write_json(pid, "run.json", {**storage.read_json(pid, "run.json", {}), "state": "error", "error": str(exc)})
        events.emit(pid, run=run, stage="workflow", tool="workflow", status="error", summary="工作流已停止", detail={"error": str(exc)})
    finally:
        with orchestrator._LOCK:
            storage.write_json(pid, "workflow.json", state)
            orchestrator._ACTIVE.pop(str(storage.project_dir(pid)), None)


def start(pid, *, production=False, revision=None, replan=True, base_url=""):
    with editing(pid):
        previous = status(pid)
        if production and (not previous["can_produce"] or revision != previous.get("plan_revision")):
            raise orchestrator.RunConflict("只能制作当前已预览且通过校验的方案，请重新预览")
        state = {"run": "w" + uuid4().hex[:12], "state": "producing" if production else "previewing",
                 "plan_revision": revision if production else None, "exports": {}, "error": None,
                 "preview": previous.get("preview") if production else None}
        storage.write_json(pid, "workflow.json", state)
        thread = threading.Thread(target=_worker, args=(pid, state, replan, base_url), daemon=True, name=f"workflow-{pid}")
        orchestrator._ACTIVE[str(storage.project_dir(pid))] = thread
        try:
            thread.start()
        except Exception:
            orchestrator._ACTIVE.pop(str(storage.project_dir(pid)), None)
            state.update(state="error", error="后台任务启动失败")
            storage.write_json(pid, "workflow.json", state)
            raise
        return {"run": state["run"], "state": "producing" if production else "previewing"}


def assert_export(pid, path):
    path = str(storage.safe_path(storage.project_dir(pid), path).relative_to(storage.project_dir(pid)))
    if path == "preview-timeline.json" and not status(pid)["current"]:
        raise orchestrator.RunConflict("预览已过期，请重新生成当前方案预览")
    if storage.read_json(pid, "workflow.json") is not None and (path in {"renders/final.mp4", "report.html", "report.json", "project.zip"}):
        if not status(pid)["can_download"]:
            raise orchestrator.RunConflict("当前方案尚未完成制作，旧成片与导出已失效")
