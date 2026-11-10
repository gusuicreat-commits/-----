from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import threading
import time

from fastapi.testclient import TestClient
import pytest

from app import config, events, main, storage
from app.agent import orchestrator as o, planner, validator
from app.ingest.facts import extract_facts

REAL_RUN = subprocess.run
REAL_CONNECT = socket.socket.connect


class InlineThread:
    def __init__(self, target, args, kwargs, **unused):
        self.target, self.args, self.kwargs = target, args, kwargs
    def start(self):
        self.target(*self.args, **self.kwargs)


@pytest.fixture
def stages(project, monkeypatch):
    pid = project["id"]
    calls = []
    monkeypatch.setattr(o.threading, "Thread", InlineThread)
    def record(name, result=None):
        def function(*args, **kwargs):
            calls.append(name)
            return deepcopy(result)
        return function
    (storage.project_dir(pid) / "docs/a.pdf").write_bytes(b"pdf")
    monkeypatch.setattr(o.ingest, "extract_facts", record("ingest", {}))
    monkeypatch.setattr(o, "prepare_model", record("model"))
    monkeypatch.setattr(o.planner, "plan", record("plan"))
    monkeypatch.setattr(o.planner, "repair", record("repair"))
    monkeypatch.setattr(o.validator, "validate", record("validate", {"issues": []}))
    monkeypatch.setattr(o, "synthesize_shots", record("tts"))
    monkeypatch.setattr(o.timeline, "build_timeline", record("timeline", {"shots": []}))
    monkeypatch.setattr(o.compose, "render_video", record("render"))
    monkeypatch.setattr(o.compose, "mux", record("compose"))
    monkeypatch.setattr(o.qa, "visual_qa", record("qa"))
    monkeypatch.setattr(o.report, "build_report", record("report"))
    return pid, calls


def test_all_stages(stages):
    pid, calls = stages
    run = o.start_run(pid, base_url="http://127.0.0.1:8031")
    assert calls == ["ingest", "model", "plan", "validate", "tts", "timeline", "render", "compose", "qa", "report"]
    state = storage.read_json(pid, "run.json")
    assert state["run"] == run and state["state"] == "done" and state["finished_at"]
    assert set(state["stage_durations_s"]) == set(o.STAGES)


@pytest.mark.parametrize("force", [False, True])
def test_paused_and_force(stages, monkeypatch, force):
    pid, calls = stages
    def validate(*args):
        calls.append("validate")
        return {"issues": [{"severity": "block", "message": "需处理"}]}
    monkeypatch.setattr(o.validator, "validate", validate)
    o.start_run(pid, force=force, base_url="http://127.0.0.1:8031")
    state = storage.read_json(pid, "run.json")
    assert state["state"] == ("done" if force else "paused")
    assert calls.count("validate") == 2 and calls.count("repair") == 1
    assert ("tts" in calls) == force and state["forced"] == force
    if not force:
        assert events.read_events(pid)[-1]["summary"] == "存在 1 个阻断问题，等待人工复核"


def test_repair_resolves_blocks(stages, monkeypatch):
    pid, calls = stages
    results = iter([{"issues": [{"severity": "block"}]}, {"issues": []}])
    monkeypatch.setattr(o.validator, "validate", lambda *args: next(results))
    o.start_run(pid, base_url="http://127.0.0.1:8031")
    assert storage.read_json(pid, "run.json")["state"] == "done"
    assert calls.count("repair") == 1


@pytest.mark.parametrize("stage", o.STAGES)
def test_from_every_stage(stages, stage):
    pid, calls = stages
    o.start_run(pid, from_stage=stage, base_url="http://127.0.0.1:8031")
    expected = list(o.STAGES[o.STAGES.index(stage):])
    expected.insert(expected.index("render"), "timeline") if "render" in expected else None
    assert calls == expected


def test_failure_preserves_products_and_can_resume(stages, monkeypatch):
    pid, calls = stages
    product = storage.project_dir(pid) / "tts/S1.mp3"
    product.write_bytes(b"retained")
    def fail(*args, **kwargs):
        raise RuntimeError("渲染失败")
    monkeypatch.setattr(o.compose, "render_video", fail)
    o.start_run(pid, base_url="http://127.0.0.1:8031")
    state = storage.read_json(pid, "run.json")
    assert state["state"] == "error" and state["stage"] == "render"
    assert "渲染失败" in state["error"] and "compose" not in calls
    assert product.read_bytes() == b"retained"
    monkeypatch.setattr(o.compose, "render_video", lambda *a, **kw: calls.append("render"))
    o.start_run(pid, from_stage="render", base_url="http://127.0.0.1:8031")
    assert storage.read_json(pid, "run.json")["state"] == "done"


def test_qa_failure_does_not_interrupt(stages, monkeypatch):
    pid, calls = stages
    def fail(*args, **kwargs):
        raise RuntimeError("图片检查失败")
    monkeypatch.setattr(o.qa, "visual_qa", fail)
    o.start_run(pid, base_url="http://127.0.0.1:8031")
    assert storage.read_json(pid, "run.json")["state"] == "done" and calls[-1] == "report"
    assert storage.read_json(pid, "issues.json")["issues"][0]["code"] == "VISUAL_QA"


def test_skip_existing_inputs(stages):
    pid, calls = stages
    storage.write_json(pid, "facts.json", {"facts": [{"id": "F_span", "status": "confirmed", "value": 88}]})
    project = storage.read_json(pid, "project.json")
    project["model"] = {"kind": "step"}
    storage.write_json(pid, "project.json", project)
    storage.write_json(pid, "shotlist.json", {"shots": [{"id": "S1"}]})
    o.start_run(pid, base_url="http://127.0.0.1:8031")
    assert not {"ingest", "model", "plan"} & set(calls)


def test_concurrent_run_conflict_and_invalid_stage(project, monkeypatch):
    pid = project["id"]
    entered, release = threading.Event(), threading.Event()
    def block(pid):
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(o.report, "build_report", block)
    with pytest.raises(ValueError, match="未知"):
        o.start_run(pid, from_stage="bad", base_url="http://127.0.0.1:8031")
    o.start_run(pid, from_stage="report", base_url="http://127.0.0.1:8031")
    assert entered.wait(2)
    worker = o._ACTIVE[str(storage.project_dir(pid))]
    try:
        with pytest.raises(o.RunConflict):
            o.start_run(pid, base_url="http://127.0.0.1:8031")
        with TestClient(main.app) as client:
            response = client.post(f"/api/projects/{pid}/run", json={"from_stage": "report"})
            assert response.status_code == 409
    finally:
        release.set()
        worker.join(5)
    assert storage.read_json(pid, "run.json")["state"] == "done"


def test_api_shots_models_runs_and_readbacks(project, monkeypatch):
    pid = project["id"]
    shot = {"id": "S1", "narration": "原台词", "params": {"from_deg": 0, "to_deg": 20},
            "review": {"status": "approved", "note": "已审"}, "narration_resolved": "原台词"}
    storage.write_json(pid, "shotlist.json", {"shots": [shot]})
    calls = []
    monkeypatch.setattr(o, "start_run", lambda pid, **kw: calls.append(kw) or "rtest")
    monkeypatch.setattr(o, "prepare_model", lambda pid, run, **kw: {"kind": "step" if kw else "parametric", "glb": "model/crane.glb"})
    monkeypatch.setattr(planner, "revise_shot", lambda *args: {"shots": [{**shot, "narration": "新台词"}]})
    with TestClient(main.app, base_url="http://localhost:9123") as client:
        prefix = f"/api/projects/{pid}"
        assert client.get(prefix + "/shotlist").json()["shots"] == [shot]
        patched = client.patch(prefix + "/shots/S1", json={"params": {"to_deg": 40}}).json()
        assert patched["params"] == {"from_deg": 0, "to_deg": 40} and patched["review"]["status"] == "pending"
        assert "narration_resolved" not in patched
        assert client.patch(prefix + "/shots/S1", json={"review": {"status": "bad"}}).status_code == 422
        assert client.patch(prefix + "/shots/S1", json={"narration": None}).status_code == 422
        assert client.patch(prefix + "/shots/missing", json={"narration": "改"}).status_code == 404
        assert client.post(prefix + "/shots/S1/revise", json={"instruction": "重写"}).json()["narration"] == "新台词"
        assert client.post(prefix + "/model/parametric").json()["kind"] == "parametric"
        assert client.post(prefix + "/model/step", files={"file": ("a.stp", b"model")}).json()["kind"] == "step"
        assert client.post(prefix + "/model/step", files={"file": ("a.txt", b"model")}).status_code == 422
        assert client.post(prefix + "/run", json={"from_stage": "validate", "force": True}).json() == {"run": "rtest"}
        assert calls[-1] == {"from_stage": "validate", "force": True, "base_url": "http://127.0.0.1:9123"}
        monkeypatch.setenv("KEPU_PORT", "8555")
        client.post(prefix + "/run", json={})
        assert calls[-1]["base_url"] == "http://127.0.0.1:8555"
        assert client.post(prefix + "/run", json={"from_stage": "bad"}).status_code == 422
        for name in ("run", "timeline", "report", "issues"):
            storage.write_json(pid, name + ".json", {"test": name})
            assert client.get(prefix + "/" + name).json() == {"test": name}


def test_parametric_model_records_actual_sources(project):
    pid = project["id"]
    storage.write_json(pid, "facts.json", {"facts": [
        {"id": "F_girder_length", "value": 104, "status": "verified"},
        {"id": "F_span", "value": 99, "status": "needs_review"}]})
    model = o.prepare_model(pid, "r1")
    assert "F_girder_length" in model["derived_from"]
    assert "F_span" not in model["derived_from"] and "F_span" in model["assumed"]
    assert (storage.project_dir(pid) / "model/crane.glb").is_file()
    assert storage.read_json(pid, "project.json")["model"] == model


@pytest.mark.slow
def test_slow_seed_replay_render_mux_report(request, monkeypatch):
    if "slow" not in request.config.getoption("markexpr"):
        pytest.skip("真实浏览器集成仅在 -m slow 时运行")
    import uvicorn
    from app.media.tts import probe_duration
    assert (config.ROOT / "web/render/render.mjs").is_file(), "缺少 T2 渲染入口 web/render/render.mjs，须先合入 T2"
    def local_run(args, **kwargs):
        assert Path(args[0]).name in {"ffmpeg", "ffprobe", "node"}, "测试禁止调用联网工具"
        return REAL_RUN(args, **kwargs)
    def local_connect(sock, address):
        assert address[0] in {"127.0.0.1", "::1"}, "测试只允许访问本机服务"
        return REAL_CONNECT(sock, address)
    monkeypatch.setattr(subprocess, "run", local_run)
    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setenv("KEPU_TTS_ENGINE", "fake")
    monkeypatch.setenv("KEPU_RENDER_MAX_S", "3")
    with TestClient(main.app) as client:
        project = client.post("/api/demo/seed").json()
    pid = project["id"]
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="error"))
    server_thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    server_thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started, "本机服务未启动"
        o.start_run(pid, base_url=f"http://127.0.0.1:{port}")
        worker = o._ACTIVE.get(str(storage.project_dir(pid)))
        if worker:
            worker.join(180)
            assert not worker.is_alive(), "集成流水线超时"
        state = storage.read_json(pid, "run.json")
        assert state["state"] == "done", state
        final = storage.project_dir(pid) / "renders/final.mp4"
        assert 2.9 <= probe_duration(final) <= 3.1
        assert (storage.project_dir(pid) / "report.html").is_file()
        logs = [json.loads(path.read_text()) for path in (storage.project_dir(pid) / "llm").glob("*.json")]
        assert {log["task"] for log in logs} >= {"extract_facts", "plan"}
        assert all(log["backend"] == "replay" for log in logs)
    finally:
        server.should_exit = True
        server_thread.join(10)
        listener.close()


def test_seed_replay_plan_is_ready_for_integration():
    project = main.seed_demo()
    pid = project["id"]
    extract_facts(pid, "r1", storage.project_dir(pid) / "docs/示例技术参数表.pdf")
    o.prepare_model(pid, "r1")
    shots = planner.plan(pid, "r1")
    assert len(shots["shots"]) == 8
    assert not [issue for issue in validator.validate(pid, "r1")["issues"] if issue["severity"] == "block"]
    logs = [json.loads(path.read_text()) for path in (storage.project_dir(pid) / "llm").glob("*.json")]
    assert all(log["backend"] == "replay" for log in logs)


def test_tts_parallel_limit_and_each_shot_event(project, monkeypatch):
    pid = project["id"]
    shots = [{"id": f"S{i}", "narration": "跨度{{F_span}}"} for i in range(8)]
    storage.write_json(pid, "shotlist.json", {"shots": shots})
    storage.write_json(pid, "facts.json", {"facts": [{"id": "F_span", "value": 88, "unit": "m"}]})
    lock = threading.Lock()
    barrier = threading.Barrier(4, timeout=3)
    active, maximum = 0, 0
    def synthesize(text, path):
        nonlocal active, maximum
        assert text == "跨度88米"
        with lock:
            active += 1
            maximum = max(maximum, active)
        barrier.wait()
        with lock:
            active -= 1
        return {"duration_s": 1, "engine": "fake"}
    monkeypatch.setattr(o.tts, "synthesize", synthesize)
    o.synthesize_shots(pid, "r1")
    assert maximum == 4
    history = events.read_events(pid)
    assert len(history) == 8
    assert {event["detail"]["shot"] for event in history} == {shot["id"] for shot in shots}


def test_tts_refreshes_analogy_before_speaking(project, monkeypatch):
    pid = project["id"]
    storage.write_json(pid, "facts.json", {"facts": [{"id": "F_girder_length", "value": 210, "unit": "m"}]})
    storage.write_json(pid, "shotlist.json", {"shots": [{"id": "S1", "narration": "{{A_length}}"}],
                       "analogies": [{"id": "A_length", "fact": "F_girder_length", "ref": "football_field",
                                      "axis": "length", "ratio": 1, "text": "旧类比"}]})
    spoken = []
    monkeypatch.setattr(o.tts, "synthesize", lambda text, path: spoken.append(text) or {"duration_s": 1, "engine": "fake"})
    o.synthesize_shots(pid, "r1")
    analogy = storage.read_json(pid, "shotlist.json")["analogies"][0]
    assert analogy["ratio"] == 2
    assert spoken == [analogy["text"]] and spoken != ["旧类比"]


@pytest.mark.parametrize('mode,fail', [('photoreal',False),('photoreal',True),('standard',False)])
def test_render_backgrounds_are_written_only_to_timeline(stages, monkeypatch, mode, fail):
    pid,calls = stages
    project = storage.read_json(pid, 'project.json')
    storage.write_json(pid, 'project.json', {**project,'render_mode':mode})
    storage.write_json(pid, 'facts.json', {'facts':[]})
    shots = [{'id':'S1','kind':'title','params':{},'start':0,'end':.1},
             {'id':'S2','kind':'outro','params':{},'start':.1,'end':.2}]
    storage.write_json(pid, 'shotlist.json', {'shots':shots})
    def build(_):
        calls.append('timeline')
        return {'fps':30,'shots':deepcopy(shots)}
    monkeypatch.setattr(o.timeline, 'build_timeline', build)
    monkeypatch.setattr(o.blender, 'blender_executable', lambda:'/blender')
    def render(args, timeout, progress):
        if fail:
            raise RuntimeError('模拟失败')
        directory = Path(args[args.index('--out')+1])
        (directory/'anchors.json').write_text('{}')
        for i in range(1,4):
            (directory/f'frame_{i:05d}.jpg').write_bytes(b'frame')
    monkeypatch.setattr(o.blender, '_render', render)
    observed = []
    monkeypatch.setattr(o.compose, 'render_video', lambda *a,**kw:observed.append(storage.read_json(pid,'timeline.json')))
    o.start_run(pid, from_stage='render', base_url='http://127.0.0.1:8031')
    assert storage.read_json(pid, 'run.json')['state'] == 'done'
    assert len(observed) == 1
    assert ('bg' in observed[0]['shots'][0]) == (mode == 'photoreal' and not fail)
    assert 'bg' not in observed[0]['shots'][1]
    assert storage.read_json(pid, 'shotlist.json') == {'shots':shots}
    assert any(e['status']=='warn' and e['tool']=='render.blender' for e in events.read_events(pid)) == fail
