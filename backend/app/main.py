"""资料入库 HTTP 服务。"""
import asyncio
import json
import logging
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, events, storage
from app.ingest.facts import FactPatch, extract_facts, update_fact
from app.llm import LLMError
from app.agent import orchestrator, planner, workflow
from app.media.blender import blender_executable

app = FastAPI(title="起重机科普视频智能体")
logger = logging.getLogger(__name__)
_RUNS: dict[str, int] = {}


@app.exception_handler(KeyError)
async def missing_handler(request: object, exc: KeyError) -> JSONResponse:
    return JSONResponse({"error": str(exc.args[0]) if exc.args else "记录不存在"}, status_code=404)


@app.exception_handler(ValueError)
async def value_handler(request: object, exc: ValueError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=422)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: object, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse({"error": "请求参数格式无效，请检查必填字段、类型和取值"}, status_code=422)


@app.exception_handler(StarletteHTTPException)
async def http_handler(request: object, exc: StarletteHTTPException) -> JSONResponse:
    defaults = {404: "请求的资源不存在", 405: "请求方法不支持", 403: "不允许访问此路径"}
    detail = exc.detail if isinstance(exc.detail, str) and re.search(r"[\u4e00-\u9fff]", exc.detail) else defaults.get(exc.status_code, "请求失败")
    return JSONResponse({"error": detail}, status_code=exc.status_code)


@app.exception_handler(LLMError)
async def llm_handler(request: object, exc: LLMError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=502)


@app.exception_handler(Exception)
async def general_handler(request: object, exc: Exception) -> JSONResponse:
    logger.exception("处理请求失败")
    return JSONResponse({"error": "处理请求失败，请检查输入资料或服务日志"}, status_code=500)


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    brief: str


@app.post("/api/projects")
def create_project(body: ProjectInput) -> dict:
    return storage.new_project(body.name, body.brief)


@app.get("/api/projects")
def get_projects() -> list[dict]:
    return storage.list_projects()


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    project = storage.read_json(pid, "project.json")
    from app.agent.scale_film import ready
    return {**project, "render_mode": project.get("render_mode", "standard"),
            "scale_film_ready": ready(pid),
            "blender_available": blender_executable() is not None}


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    render_mode: Literal["standard", "photoreal", "scale_film"] | None = None
    director_recipe: Literal["off", "auto", "scale", "motion", "structure"] | None = None
    target_s: float | None = Field(default=None, ge=10, le=120, allow_inf_nan=False)


@app.patch("/api/projects/{pid}/settings")
@workflow.project_mutation
def patch_settings(pid: str, body: SettingsInput) -> dict:
    with storage.LOCK:
        project = storage.read_json(pid, "project.json")
        for key, value in body.model_dump(exclude_none=True).items():
            project[key] = value
        if project.get("render_mode") == "scale_film":
            from app.agent.scale_film import settings
            settings(project)
        storage.write_json(pid, "project.json", project)
    return get_project(pid)


@app.get("/api/projects/{pid}/llm")
def get_llm_logs(pid: str) -> dict[str, list[dict[str, object]]]:
    directory = storage.safe_path(storage.project_dir(pid), "llm")
    fields = ("task", "backend", "cost_usd", "started_at", "duration_s")
    calls: list[dict[str, object]] = []
    with storage.LOCK:
        for path in sorted(directory.glob("*.json")):
            if path.is_file():
                log = storage.read_json(pid, f"llm/{path.name}")
                calls.append({"file": path.name, **{field: log.get(field) for field in fields}})
    return {"calls": calls}


def next_run(pid: str) -> str:
    with storage.LOCK:
        key = str(storage.project_dir(pid))
        previous = [int(event["run"][1:]) for event in events.read_events(pid)
                    if re.fullmatch(r"r\d+", event["run"])]
        number = max([_RUNS.get(key, 0), *previous], default=0) + 1
        _RUNS[key] = number
        return f"r{number}"


def save_upload(pid: str, folder: str, file: UploadFile) -> Path:
    name = file.filename or ""
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError("上传文件名无效")
    with storage.LOCK:
        root = storage.project_dir(pid) / folder
        path = storage.safe_path(root, name)
        index = 1
        while path.exists():
            path = storage.safe_path(root, f"{Path(name).stem}_{index}{Path(name).suffix}")
            index += 1
        try:
            with path.open("xb") as out:
                shutil.copyfileobj(file.file, out)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()
    return path


@workflow.project_mutation
def extract_background(pid: str, run: str, path: Path) -> None:
    try:
        extract_facts(pid, run, path)
    except Exception:
        # 具体工具的失败已写入事件，后台异常不改变已发送的响应。
        logger.exception("文档后台提取失败，详情见项目事件")


@app.post("/api/projects/{pid}/docs")
@workflow.project_mutation
def upload_document(pid: str, background_tasks: BackgroundTasks, file: UploadFile = File(...),
                    sync: int = Query(0, ge=0, le=1)) -> dict:
    storage.project_dir(pid)
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise ValueError("仅支持上传 PDF 文档")
    path = save_upload(pid, "docs", file)
    run = next_run(pid)
    if sync:
        return extract_facts(pid, run, path)
    background_tasks.add_task(extract_background, pid, run, path)
    return {"accepted": True, "run": run}


@app.get("/api/projects/{pid}/facts")
def get_facts(pid: str) -> dict:
    return storage.read_json(pid, "facts.json", {"facts": []})


@app.patch("/api/projects/{pid}/facts/{fid}")
@workflow.project_mutation
def patch_fact(pid: str, fid: str, patch: FactPatch) -> dict:
    return update_fact(pid, fid, patch.model_dump(exclude_unset=True))


@app.post("/api/projects/{pid}/assets")
@workflow.project_mutation
def upload_asset(pid: str, file: UploadFile = File(...), provenance: Literal["own", "reference"] = Form(...),
                 title: str = Form(""), tags: str = Form(""), credit: str = Form("")) -> dict:
    storage.project_dir(pid)
    if provenance == "reference" and not credit.strip():
        raise ValueError("参考素材必须填写作者、许可证与来源链接")
    mime = mimetypes.guess_type(file.filename or "")[0] or ""
    if not mime.startswith(("image/", "video/")):
        raise ValueError("仅支持图片或视频素材")
    with storage.LOCK:
        path = save_upload(pid, "assets", file)
        result = storage.read_json(pid, "assets.json", {"assets": []})
        number = 1
        ids = {item["id"] for item in result["assets"]}
        while f"IMG_{number:02d}" in ids:
            number += 1
        asset = {"id": f"IMG_{number:02d}", "kind": "video" if mime.startswith("video/") else "image",
                 "file": f"assets/{path.name}", "provenance": provenance, "title": title,
                 "tags": [tag.strip() for tag in tags.split(",") if tag.strip()], "credit": credit, "duration_s": None}
        result["assets"].append(asset)
        storage.write_json(pid, "assets.json", result)
    return asset


@app.get("/api/projects/{pid}/assets")
def get_assets(pid: str) -> dict:
    return storage.read_json(pid, "assets.json", {"assets": []})


async def event_stream(pid: str) -> AsyncIterator[str]:
    history, queue = events.replay_and_subscribe(pid)
    try:
        for event in history:
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            except asyncio.TimeoutError:
                yield ": ping\n\n"
    finally:
        events.unsubscribe(pid, queue)


@app.get("/api/projects/{pid}/events")
async def get_events(pid: str) -> StreamingResponse:
    storage.project_dir(pid)
    return StreamingResponse(event_stream(pid), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/demo/seed")
def seed_demo() -> dict:
    project = storage.new_project("1230t 造船门机科普", "做一条 45 秒左右的科普短视频，让普通观众直观感受这台门机有多大、焊缝有多准，语气亲切、有画面感")
    pid = project["id"]
    directory = storage.project_dir(pid)
    shutil.copyfile(config.SAMPLES_DIR / "示例技术参数表.pdf", directory / "docs/示例技术参数表.pdf")
    credits = json.loads((config.SAMPLES_DIR / "assets/CREDITS.json").read_text(encoding="utf-8"))
    assets = []
    for item in credits:
        name = item["file"]
        source = storage.safe_path(config.SAMPLES_DIR / "assets", name)
        target = storage.safe_path(directory / "assets", name)
        shutil.copyfile(source, target)
        tags = ["门式起重机", "造船厂"] if any(word in name.lower() for word in ("odense", "belfast", "ulsan")) else ["焊接"] if "tig" in name.lower() else ["钢结构"] if "girder" in name.lower() else []
        assets.append({"id": item["id"], "kind": "image", "file": "assets/" + name,
                       "provenance": "reference", "title": item["title"], "tags": tags,
                       "credit": " / ".join([item["author"], item["license"], item["source"]]), "duration_s": None})
    storage.write_json(pid, "assets.json", {"assets": assets})
    return project



class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_stage: Literal["ingest", "model", "plan", "validate", "tts", "render", "compose", "qa", "report"] | None = None
    force: bool = False


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "approved", "changes"]
    note: str = ""


class ShotPatch(BaseModel):
    duration_s: float | None = Field(default=None, gt=0, le=120, allow_inf_nan=False)
    model_config = ConfigDict(extra="forbid")
    narration: str | None = None
    params: dict | None = None
    review: ReviewInput | None = None


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1)


@app.exception_handler(orchestrator.RunConflict)
async def run_conflict_handler(request: object, exc: orchestrator.RunConflict) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=409)


@app.post("/api/projects/{pid}/model/step")
@workflow.project_mutation
def upload_step(pid: str, file: UploadFile = File(...)) -> dict:
    storage.project_dir(pid)
    if Path(file.filename or "").suffix.lower() not in {".step", ".stp"}:
        raise ValueError("仅支持上传 STEP 或 STP 模型")
    path = save_upload(pid, "model", file)
    return orchestrator.prepare_model(pid, next_run(pid), step_path=path)


@app.post("/api/projects/{pid}/model/parametric")
@workflow.project_mutation
def create_parametric(pid: str) -> dict:
    return orchestrator.prepare_model(pid, next_run(pid))


def backend_url(request: Request) -> str:
    configured = os.environ.get("KEPU_PORT")
    port = int(configured) if configured else request.url.port or (443 if request.url.scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise ValueError("服务端口无效")
    return f"http://127.0.0.1:{port}"


@app.post("/api/projects/{pid}/run")
def run_project(pid: str, body: RunInput, request: Request) -> dict:
    if storage.read_json(pid, "workflow.json") is not None:
        raise orchestrator.RunConflict("此项目使用分镜预览流程，请确认当前方案后点击制作")
    return {"run": orchestrator.start_run(pid, from_stage=body.from_stage, force=body.force, base_url=backend_url(request))}


@app.get("/api/projects/{pid}/run")
def get_run(pid: str) -> dict:
    return storage.read_json(pid, "run.json", {})


@app.get("/api/projects/{pid}/shotlist")
def get_shotlist(pid: str) -> dict:
    data = storage.read_json(pid, "shotlist.json")
    if data is None:
        raise KeyError("尚未生成分镜")
    return data


@app.patch("/api/projects/{pid}/shots/{sid}")
@workflow.project_mutation
def patch_shot(pid: str, sid: str, body: ShotPatch) -> dict:
    patch = body.model_dump(exclude_unset=True)
    if any(value is None for value in patch.values()):
        raise ValueError("镜头字段不能为 null")
    with storage.LOCK:
        data = storage.read_json(pid, "shotlist.json", {"shots": []})
        for shot in data["shots"]:
            if shot["id"] == sid:
                if "params" in patch:
                    patch["params"] = {**shot.get("params", {}), **patch["params"]}
                if any(key in patch for key in ("narration", "params", "duration_s")):
                    shot["human_edited"] = True
                    shot.pop("narration_resolved", None)
                    shot["review"] = {"status": "pending", "note": ""}
                shot.update(patch)
                storage.write_json(pid, "shotlist.json", data)
                return shot
    raise KeyError("镜头不存在")


@app.post("/api/projects/{pid}/shots/{sid}/revise")
@workflow.project_mutation
def revise_shot(pid: str, sid: str, body: RevisionInput) -> dict:
    data = storage.read_json(pid, "shotlist.json", {"shots": []})
    if not any(shot["id"] == sid for shot in data["shots"]):
        raise KeyError("镜头不存在")
    result = planner.revise_shot(pid, next_run(pid), sid, body.instruction)
    return next(shot for shot in result["shots"] if shot["id"] == sid)


@app.get("/api/projects/{pid}/issues")
def get_issues(pid: str) -> dict:
    return storage.read_json(pid, "issues.json", {"issues": []})


@app.get("/api/projects/{pid}/timeline")
def get_timeline(pid: str) -> dict:
    return storage.read_json(pid, "timeline.json", {})


@app.get("/api/projects/{pid}/report")
def get_report(pid: str) -> dict:
    if storage.read_json(pid, "workflow.json") is not None and not workflow.status(pid)["can_download"]:
        return {}
    return storage.read_json(pid, "report.json", {})


def static_file(root: Path, path: str, *, fallback: bool = False) -> FileResponse | HTMLResponse:
    if fallback and not root.is_dir():
        return HTMLResponse("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>起重机科普</title><p>后端服务已启动，操作界面尚未就绪。</p></html>")
    try:
        target = storage.safe_path(root, path or "index.html")
        if target.is_dir():
            target = storage.safe_path(root, str(target.relative_to(root)) + "/index.html")
    except ValueError as exc:
        raise HTTPException(403, "不允许访问此路径") from exc
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)


class WorkflowBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: str = Field(min_length=1)
    target_s: float = Field(default=30, ge=10, le=120, allow_inf_nan=False)
    engine: Literal["threejs", "blender"] = "threejs"
    content: Literal["auto", "scale", "motion", "structure"] = "auto"


class WorkflowPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replan: bool = True


class WorkflowProduce(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_revision: str = Field(min_length=1)


@app.get("/api/workflow/capabilities")
def workflow_capabilities() -> dict:
    return workflow.capabilities()


@app.get("/api/projects/{pid}/workflow")
def workflow_status(pid: str) -> dict:
    return workflow.status(pid)


@app.patch("/api/projects/{pid}/workflow/brief")
def workflow_brief(pid: str, body: WorkflowBrief) -> dict:
    return workflow.brief(pid, body.model_dump())


@app.post("/api/projects/{pid}/workflow/preview")
def workflow_preview(pid: str, body: WorkflowPreview) -> dict:
    return workflow.start(pid, replan=body.replan)


@app.post("/api/projects/{pid}/workflow/produce")
def workflow_produce(pid: str, body: WorkflowProduce, request: Request) -> dict:
    return workflow.start(pid, production=True, revision=body.plan_revision, base_url=backend_url(request))


@app.get("/files/{pid}/{path:path}")
def project_file(pid: str, path: str):
    try:
        workflow.assert_export(pid, path)
    except ValueError as exc:
        raise HTTPException(403, "不允许访问此路径") from exc
    return static_file(storage.project_dir(pid), path)


@app.get("/player/{path:path}")
def player_file(path: str):
    return static_file(config.WEB_DIR / "player", path)


@app.get("/vendor/three/{path:path}")
def vendor_file(path: str):
    return static_file(config.WEB_DIR / "node_modules/three", path)


@app.get("/{path:path}")
def app_file(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "接口不存在")
    return static_file(config.WEB_DIR / "app", path, fallback=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("KEPU_PORT", "8031")))
