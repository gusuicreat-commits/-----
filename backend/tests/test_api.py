import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app import config, events, main, storage


@pytest.fixture
def client():
    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield client


def test_project_api(client):
    project = client.post("/api/projects", json={"name": "项目一", "brief": "说明"}).json()
    pid = project["id"]
    assert client.get("/api/projects").json() == [project]
    detail = client.get(f"/api/projects/{pid}").json()
    assert {key: detail[key] for key in project} == project
    assert detail["render_mode"] == "standard"
    assert isinstance(detail["blender_available"], bool)
    assert client.get(f"/api/projects/{pid}/facts").json() == {"facts": []}
    assert client.get(f"/api/projects/{pid}/assets").json() == {"assets": []}
    assert client.get("/api/projects/invalid").status_code == 404
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    assert client.get(f"/api/projects/{pid}/shotlist").status_code == 404


def test_seed_sync_extract_patch_and_files(client, sample_pdf):
    response = client.post("/api/demo/seed")
    assert response.status_code == 200
    project = response.json()
    pid = project["id"]
    assert project["name"] == "1230t 造船门机科普"
    assert "45 秒" in project["brief"]
    assert not (storage.project_dir(pid) / "facts.json").exists()
    assets = client.get(f"/api/projects/{pid}/assets").json()["assets"]
    assert len(assets) == 5
    assert all(item["provenance"] == "reference" and " / " in item["credit"] for item in assets)
    assert next(item for item in assets if item["id"] == "IMG_TIG")["tags"] == ["焊接"]
    data = sample_pdf.read_bytes()
    response = client.post(f"/api/projects/{pid}/docs?sync=1", files={"file": (sample_pdf.name, data, "application/pdf")})
    assert response.status_code == 200, response.text
    assert len(response.json()["facts"]) == 14
    fact = client.patch(f"/api/projects/{pid}/facts/F_leg_height", json={"value": 41}).json()
    assert fact["value"] == 41 and fact["status"] == "confirmed"
    assert client.patch(f"/api/projects/{pid}/facts/F_leg_height", json={"status": "unknown"}).status_code == 422
    assert client.patch(f"/api/projects/{pid}/facts/F_leg_height", json={"value": None}).status_code == 422
    assert client.get(f"/files/{pid}/docs/{sample_pdf.name}").content == data
    assert (storage.project_dir(pid) / "docs/示例技术参数表_1.pdf").read_bytes() == data


def test_upload_assets(client, project):
    pid = project["id"]
    url = f"/api/projects/{pid}/assets"
    files = {"file": ("照片.png", b"image", "image/png")}
    assert client.post(url, files=files, data={"provenance": "reference"}).status_code == 422
    response = client.post(url, files=files, data={"provenance": "reference", "credit": "作者 / 许可 / 来源", "title": "焊接", "tags": "焊接, 钢结构"})
    assert response.status_code == 200
    first = response.json()
    assert first["id"] == "IMG_01" and first["tags"] == ["焊接", "钢结构"]
    second = client.post(url, files=files, data={"provenance": "own"}).json()
    assert second["id"] == "IMG_02" and second["file"] != first["file"]
    assert len(client.get(url).json()["assets"]) == 2
    assert client.post(url, files={"file": ("../secret.png", b"bad")}, data={"provenance": "own"}).status_code == 422


def test_background_upload_runs_and_errors(client, project, sample_pdf, monkeypatch):
    pid = project["id"]
    url = f"/api/projects/{pid}/docs"
    files = {"file": (sample_pdf.name, sample_pdf.read_bytes(), "application/pdf")}
    response = client.post(url, files=files)
    assert response.json() == {"accepted": True, "run": "r1"}
    assert len(client.get(f"/api/projects/{pid}/facts").json()["facts"]) == 14
    monkeypatch.setenv("KEPU_LLM_CASSETTES", str(storage.project_dir(pid) / "empty"))
    assert client.post(url, files=files).json() == {"accepted": True, "run": "r2"}
    assert events.read_events(pid)[-1]["status"] == "error"
    sync_response = client.post(url + "?sync=1", files=files)
    assert sync_response.status_code == 502 and "缺少录制" in sync_response.json()["error"]
    assert client.post(url, files={"file": ("bad.txt", b"bad")}).status_code == 422


def test_sse_replay_and_disconnect(client, project):
    pid = project["id"]
    event = events.emit(pid, run="r1", stage="ingest", tool="pdf.extract", status="ok", summary="完成")

    async def request_stream():
        # 在测试客户端的事件循环内驱动真实 ASGI 断开，避免无限流被客户端缓冲。
        sent = []
        disconnected = asyncio.Event()
        requested = False
        async def receive():
            nonlocal requested
            if not requested:
                requested = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and b"data: " in message.get("body", b""):
                disconnected.set()
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                 "method": "GET", "scheme": "http", "path": f"/api/projects/{pid}/events", "root_path": "",
                 "query_string": b"", "headers": [], "client": ("testclient", 123), "server": ("testserver", 80)}
        await asyncio.wait_for(main.app(scope, receive, send), 2)
        return sent

    messages = client.portal.call(request_stream)
    assert messages[0]["status"] == 200
    assert b"text/event-stream" in dict(messages[0]["headers"])[b"content-type"]
    bodies = b"".join(message.get("body", b"") for message in messages)
    assert json.loads(bodies.decode().strip().removeprefix("data: ")) == event
    assert pid not in events._SUBSCRIBERS


@pytest.mark.asyncio
async def test_sse_live_and_ping(project, monkeypatch):
    pid = project["id"]
    stream = main.event_stream(pid)
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    event = events.emit(pid, run="r1", stage="ingest", tool="pdf.extract", status="ok", summary="完成")
    assert json.loads((await asyncio.wait_for(pending, 1)).removeprefix("data: ")) == event
    async def timeout(awaitable, timeout):
        assert timeout == 15
        awaitable.close()
        raise asyncio.TimeoutError
    monkeypatch.setattr(main.asyncio, "wait_for", timeout)
    assert await anext(stream) == ": ping\n\n"
    await stream.aclose()
    assert pid not in events._SUBSCRIBERS


def test_traversal_and_static_pages(client, project, tmp_path, monkeypatch):
    pid = project["id"]
    secret = tmp_path / "secret.txt"
    secret.write_text("不可读取")
    (storage.project_dir(pid) / "outside").symlink_to(tmp_path, target_is_directory=True)
    for path in ("%2e%2e/secret.txt", "outside/secret.txt", "%2fetc/passwd"):
        response = client.get(f"/files/{pid}/{path}")
        assert response.status_code == 403
        assert "不可读取" not in response.text
    monkeypatch.setattr(config, "WEB_DIR", tmp_path / "web")
    assert "界面尚未就绪" in client.get("/").text
    for directory, url in (("app", "/"), ("player", "/player/"), ("node_modules/three", "/vendor/three/")):
        root = config.WEB_DIR / directory
        root.mkdir(parents=True)
        (root / "index.html").write_text("测试页面", encoding="utf-8")
        assert client.get(url).text == "测试页面"
    assert client.get("/files/p00000000/a").status_code == 404
