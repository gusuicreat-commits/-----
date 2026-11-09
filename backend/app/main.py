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

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, events, storage
from app.ingest.facts import FactPatch, extract_facts, update_fact
from app.llm import LLMError

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
    return storage.read_json(pid, "project.json")


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


def extract_background(pid: str, run: str, path: Path) -> None:
    try:
        extract_facts(pid, run, path)
    except Exception:
        # 具体工具的失败已写入事件，后台异常不改变已发送的响应。
        logger.exception("文档后台提取失败，详情见项目事件")


@app.post("/api/projects/{pid}/docs")
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
def patch_fact(pid: str, fid: str, patch: FactPatch) -> dict:
    return update_fact(pid, fid, patch.model_dump(exclude_unset=True))


@app.post("/api/projects/{pid}/assets")
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


@app.get("/files/{pid}/{path:path}")
def project_file(pid: str, path: str):
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
