"""Offline contract tests; mocked planner/renderers, no live generation claims."""
from copy import deepcopy
import threading

from fastapi.testclient import TestClient
import pytest
from app import main, storage
from app.agent import workflow as w


class InlineThread:
    def __init__(self, target, args, **kwargs):
        self.target, self.args = target, args
    def start(self):
        self.target(*self.args)


@pytest.fixture
def setup(project, monkeypatch):
    pid = project["id"]
    p = storage.read_json(pid, "project.json")
    p.update(model={"kind": "parametric", "glb": "model/crane.glb"})
    storage.write_json(pid, "project.json", p)
    shots = {"title": "测试", "shots": [{"id": "S1", "kind": "model_orbit", "source": "model", "duration_s": 10,
              "narration": "看看模型", "params": {}, "fact_refs": [], "asset_refs": [], "claims": [], "review": {"status": "pending"}}], "analogies": []}
    calls = []
    def plan(*args):
        calls.append("plan")
        storage.write_json(pid, "shotlist.json", deepcopy(shots))
        return shots
    monkeypatch.setattr(w, "_model_current", lambda pid: True)
    monkeypatch.setattr(w, "_ensure_model_current", lambda *args: None)
    monkeypatch.setattr(w.threading, "Thread", InlineThread)
    monkeypatch.setattr(w.planner, "plan", plan)
    monkeypatch.setattr(w.validator, "validate", lambda *args: {"issues": []})
    client = TestClient(main.app, raise_server_exceptions=False)
    client.patch(f"/api/projects/{pid}/workflow/brief", json={"brief": "只讲尺度", "engine": "threejs", "content": "scale", "target_s": 10})
    return pid, client, calls


def test_preview_edit_stales_and_produce_uses_reviewed_plan(setup, monkeypatch):
    pid, c, calls = setup
    base = f"/api/projects/{pid}"
    assert c.post(base + "/workflow/preview", json={}).status_code == 200
    status = c.get(base + "/workflow").json()
    assert status["state"] == "preview_ready" and status["can_produce"]
    assert calls == ["plan"]
    assert not (storage.project_dir(pid) / "renders/final.mp4").exists()
    preview = c.get(status["preview"]["timeline_url"]).json()
    assert preview["audio"] is None and preview["duration_s"] == 10
    revision = status["plan_revision"]
    assert c.patch(base + "/shots/S1", json={"duration_s": 12}).status_code == 200
    assert c.get(base + "/workflow").json()["state"] == "stale"
    assert c.get(status["preview"]["timeline_url"]).status_code == 409
    assert c.post(base + "/workflow/produce", json={"plan_revision": revision}).status_code == 409
    assert c.post(base + "/workflow/preview", json={"replan": False}).status_code == 200
    revised = c.get(base + "/workflow").json()["plan_revision"]
    def produce(pid, run, url, rev):
        calls.append("produce")
        assert rev == revised
        assert storage.read_json(pid, "shotlist.json")["shots"][0]["duration_s"] == 12
        (storage.project_dir(pid) / "renders/final.mp4").write_bytes(b"mock mp4")
        return {"mp4": f"/files/{pid}/renders/final.mp4"}
    monkeypatch.setattr(w, "_production", produce)
    c.post(base + "/workflow/produce", json={"plan_revision": revised})
    done = c.get(base + "/workflow").json()
    assert done["state"] == "production_done" and done["can_download"]
    assert calls == ["plan", "produce"]
    assert c.get(done["exports"]["mp4"]).content == b"mock mp4"
    c.patch(base + "/shots/S1", json={"narration": "改过"})
    assert c.get(done["exports"]["mp4"]).status_code == 409
    assert not c.get(base + "/workflow").json()["exports"]
    assert c.post(base + "/run", json={}).status_code == 409


def test_content_engine_independent_and_missing_engine_blocks(setup, monkeypatch):
    pid, c, _ = setup
    monkeypatch.setattr(w.blender, "blender_executable", lambda: None)
    c.patch(f"/api/projects/{pid}/workflow/brief", json={"brief": "只讲尺度", "engine": "blender", "content": "scale", "target_s": 20})
    p = storage.read_json(pid, "project.json")
    assert p["production_engine"] == "blender" and p["director_recipe"] == "scale" and p["render_mode"] == "standard"
    c.post(f"/api/projects/{pid}/workflow/preview", json={})
    state = c.get(f"/api/projects/{pid}/workflow").json()
    assert state["state"] == "blocked" and not state["can_produce"]
    assert any("未找到 Blender" in i["message"] for i in state["issues"])


def test_failed_preview_concurrent_edit_and_legacy_run_rejected(setup, monkeypatch):
    pid, c, _ = setup
    key = str(storage.project_dir(pid))
    w.orchestrator._ACTIVE[key] = object()
    try:
        assert c.patch(f"/api/projects/{pid}/shots/S1", json={"duration_s": 3}).status_code == 409
        assert c.post(f"/api/projects/{pid}/workflow/preview", json={}).status_code == 409
    finally:
        w.orchestrator._ACTIVE.pop(key)
    def fail(*args):
        raise RuntimeError("明确的模型失败")
    monkeypatch.setattr(w.planner, "plan", fail)
    c.post(f"/api/projects/{pid}/workflow/preview", json={})
    state = c.get(f"/api/projects/{pid}/workflow").json()
    assert state["state"] == "error" and "明确的模型失败" in state["error"]
    assert key not in w.orchestrator._ACTIVE


def test_production_validation_cannot_be_forced(setup, monkeypatch):
    pid, c, _ = setup
    c.post(f"/api/projects/{pid}/workflow/preview", json={})
    revision = w.status(pid)["plan_revision"]
    monkeypatch.setattr(w.validator, "validate", lambda *a: {"issues": [{"severity": "block", "message": "有问题"}]})
    with pytest.raises(ValueError, match="阻断"):
        w._production(pid, "test", "http://localhost", revision)


def test_blender_keyframe_invokes_single_frame_in_revision_directory(setup, monkeypatch):
    pid, c, _ = setup
    c.post(f"/api/projects/{pid}/workflow/preview", json={})
    preview = storage.read_json(pid, "preview-timeline.json")
    monkeypatch.setattr(w.blender, "blender_executable", lambda: "/mock/blender")
    args_seen = []
    def render(args, timeout, on_line):
        from pathlib import Path
        args_seen.append(args)
        out = Path(args[args.index("--out") + 1])
        (out / "still_eevee.png").write_bytes(b"mock png")
    monkeypatch.setattr(w.blender, "_render", render)
    result = w.blender.preview_keyframes(pid, "test", preview, "abc123")
    assert "--still-at" in args_seen[0] and "--skip-video" in args_seen[0]
    assert "abc123" in result[0]["url"] and result[0]["engine"] == "blender"


def test_production_pipeline_never_replans_and_emits_current_package(setup, monkeypatch):
    pid, c, calls = setup
    c.post(f"/api/projects/{pid}/workflow/preview", json={})
    revision = w.status(pid)["plan_revision"]
    calls.clear()
    monkeypatch.setattr(w.orchestrator, "synthesize_shots", lambda *a: calls.append("tts"))
    monkeypatch.setattr(w.timeline, "build_timeline", lambda *a: {"shots": [], "duration_s": 10})
    monkeypatch.setattr(w.blender, "render_model_shots", lambda *a: {})
    monkeypatch.setattr(w.compose, "render_video", lambda *a, **kw: calls.append("render"))
    def mux(*a):
        calls.append("mux")
        (storage.project_dir(pid) / "renders/final.mp4").write_bytes(b"mock generated")
    monkeypatch.setattr(w.compose, "mux", mux)
    monkeypatch.setattr(w.qa, "visual_qa", lambda *a, **kw: None)
    monkeypatch.setattr(w.report, "build_report", lambda *a: calls.append("report"))
    output = w._production(pid, "test", "http://localhost", revision)
    assert calls == ["tts", "render", "mux", "report"]
    assert output["mp4"].endswith("/renders/final.mp4")
    import zipfile
    with zipfile.ZipFile(storage.project_dir(pid) / "project.zip") as archive:
        assert "shotlist.json" in archive.namelist()


def test_internal_blender_cache_readable_while_final_exports_blocked(setup):
    pid, c, _ = setup
    root = storage.project_dir(pid)
    (root / "renders/blender").mkdir()
    (root / "renders/blender/background.mp4").write_bytes(b"internal cache")
    (root / "renders/final.mp4").write_bytes(b"old final")
    storage.write_json(pid, "workflow.json", {"state": "producing"})
    assert c.get(f"/files/{pid}/renders/blender/background.mp4").status_code == 200
    assert c.get(f"/files/{pid}/renders/final.mp4").status_code == 409


def test_binary_source_and_export_tamper_change_revision_even_if_mtime_preserved(setup):
    import os
    pid, c, _ = setup
    root = storage.project_dir(pid)
    asset = root / "assets/sample.jpg"
    asset.write_bytes(b"first")
    before = asset.stat()
    revision = w.fingerprint(pid)
    asset.write_bytes(b"other")
    os.utime(asset, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert w.fingerprint(pid) != revision
    final = root / "renders/final.mp4"
    final.write_bytes(b"first")
    revision = w.fingerprint(pid)
    exports = {"mp4": f"/files/{pid}/renders/final.mp4"}
    w._seal_exports(pid, "wtest", revision, exports)
    storage.write_json(pid, "workflow.json", {"state": "production_done", "run": "wtest", "plan_revision": revision, "exports": exports})
    assert w.status(pid)["can_download"]
    before = final.stat()
    final.write_bytes(b"other")
    os.utime(final, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert not w.status(pid)["can_download"]
    assert c.get(exports["mp4"]).status_code == 409


def test_unchanged_old_final_not_published_when_mux_produces_nothing(setup, monkeypatch):
    pid, c, _ = setup
    c.post(f"/api/projects/{pid}/workflow/preview", json={})
    revision = w.status(pid)["plan_revision"]
    (storage.project_dir(pid) / "renders/final.mp4").write_bytes(b"old result")
    monkeypatch.setattr(w.orchestrator, "synthesize_shots", lambda *a: None)
    monkeypatch.setattr(w.timeline, "build_timeline", lambda *a: {"shots": [], "duration_s": 10})
    monkeypatch.setattr(w.blender, "render_model_shots", lambda *a: {})
    monkeypatch.setattr(w.compose, "render_video", lambda *a, **kw: None)
    monkeypatch.setattr(w.compose, "mux", lambda *a: None)
    with pytest.raises(ValueError, match="拒绝沿用旧成片"):
        w._production(pid, "test", "http://localhost", revision)


def test_advanced_studio_refresh_gets_succeed_without_exposing_unpublished_report(setup):
    pid, c, _ = setup
    c.post(f"/api/projects/{pid}/workflow/preview", json={})
    storage.write_json(pid, "report.json", {"project": {"name": "旧报告"}, "shots": [{"narration": "旧台词"}]})
    root = storage.project_dir(pid)
    (root / "report.html").write_text("旧报告", encoding="utf-8")
    (root / "renders/final.mp4").write_bytes(b"old movie")
    paths = ['', '/facts', '/assets', '/shotlist', '/issues', '/timeline', '/report', '/run']
    for path in paths:
        response = c.get(f"/api/projects/{pid}{path}")
        assert response.status_code == 200, (path, response.text)
    assert c.get(f"/api/projects/{pid}/report").json() == {}
    for path in ('report.json', 'report.html', 'renders/final.mp4'):
        assert c.get(f"/files/{pid}/{path}").status_code == 409
    c.patch(f"/api/projects/{pid}/shots/S1", json={"duration_s": 11})
    assert c.get(f"/api/projects/{pid}/report").json() == {}


@pytest.mark.parametrize('rounds_needed', [1, 2, 3])
def test_generated_claim_repairs_are_bounded_and_revalidated(setup, monkeypatch, rounds_needed):
    pid, c, _ = setup
    attempts = []
    def validate(*args):
        return {"issues": [] if len(attempts) >= rounds_needed else [
            {"shot": "S1", "severity": "block", "code": "UNSUPPORTED_CLAIM", "message": "断言无依据"}]}
    monkeypatch.setattr(w.validator, "validate", validate)
    monkeypatch.setattr(w.planner, "repair", lambda pid, run, issues: attempts.append(deepcopy(issues)))
    c.post(f"/api/projects/{pid}/workflow/preview", json={})
    state = w.status(pid)
    assert len(attempts) == min(2, rounds_needed)
    assert state['state'] == ('blocked' if rounds_needed > 2 else 'preview_ready')
    assert state['repair_attempts'] == len(attempts)


def test_manual_preview_does_not_auto_rewrite_claims(setup, monkeypatch):
    pid, c, _ = setup
    c.post(f"/api/projects/{pid}/workflow/preview", json={})
    c.patch(f"/api/projects/{pid}/shots/S1", json={"narration": "人工写的"})
    monkeypatch.setattr(w.validator, "validate", lambda *args: {"issues": [
        {"shot": "S1", "severity": "block", "code": "UNSUPPORTED_CLAIM", "message": "无依据"}]})
    monkeypatch.setattr(w.planner, "repair", lambda *args: pytest.fail("不能自动改人工方案"))
    c.post(f"/api/projects/{pid}/workflow/preview", json={"replan": False})
    assert w.status(pid)['state'] == 'blocked'
    assert storage.read_json(pid, 'shotlist.json')['shots'][0]['narration'] == '人工写的'


@pytest.mark.parametrize('phase', ['previewing', 'producing'])
def test_status_recovers_interrupted_persisted_tasks(setup, monkeypatch, phase):
    pid, c, _ = setup
    storage.write_json(pid, 'workflow.json', {'state': phase, 'run': 'winterrupted', 'exports': {'mp4': 'old'}})
    monkeypatch.setattr(w.llm, 'provider_status', lambda: {'configured': True}, raising=False)
    response = c.get(f'/api/projects/{pid}/workflow')
    state = response.json()
    assert state['state'] == 'error' and state['interrupted'] and state['can_preview']
    assert not state['can_produce'] and not state['can_download'] and state['exports'] == {}
    assert storage.read_json(pid, 'workflow.json')['state'] == 'error'
    c.post(f'/api/projects/{pid}/workflow/preview', json={})
    assert w.status(pid)['state'] == 'preview_ready'


def test_fact_change_rebuilds_parametric_glb_rig_and_dimensions_without_replan(project, monkeypatch):
    pid = project['id']
    root = storage.project_dir(pid)
    p = storage.read_json(pid, 'project.json')
    p.update(production_engine='threejs', director_recipe='scale', target_s=10)
    storage.write_json(pid, 'project.json', p)
    facts = {'facts': [{'id': 'F_girder_length', 'name': '主梁长度', 'value': 104, 'unit': 'm', 'status': 'confirmed',
                        'source': {'doc': '参数表', 'page': 1, 'quote': '确认尺寸'}}]}
    storage.write_json(pid, 'facts.json', facts)
    w._ensure_model_current(pid, 'first')
    original = w.file_digest(root / 'model/crane.glb')
    model = storage.read_json(pid, 'project.json')['model']
    assert model['dims_check'][0]['doc_value'] == 104
    storage.write_json(pid, 'shotlist.json', {'shots': [{'id': 'S1', 'kind': 'model_orbit', 'source': 'model',
                       'duration_s': 10, 'narration': '主梁长{{F_girder_length}}。', 'params': {}, 'fact_refs': ['F_girder_length']}], 'analogies': []})
    facts['facts'][0]['value'] = 132
    storage.write_json(pid, 'facts.json', facts)
    assert not w._model_current(pid)
    monkeypatch.setattr(w.planner, 'plan', lambda *args: pytest.fail('replan=false不能重规划'))
    monkeypatch.setattr(w.validator, 'validate', lambda *args: {'issues': []})
    state = {'state': 'previewing', 'run': 'rebuild', 'exports': {}}
    w._worker(pid, state, False, '')
    assert state['state'] == 'preview_ready'
    assert w._model_current(pid)
    assert w.file_digest(root / 'model/crane.glb') != original
    model = storage.read_json(pid, 'project.json')['model']
    dims = next(row for row in model['dims_check'] if row['fact'] == 'F_girder_length')
    assert dims['doc_value'] == 132 and dims['ok'] and dims['model_value'] > 130
    assert storage.read_json(pid, 'model/rig.json')['bbox_m']['x'] > 130
    assert w.status(pid)['can_produce']


def test_active_worker_is_not_mistaken_for_interrupted_task(setup):
    pid, _, _ = setup
    key = str(storage.project_dir(pid))
    storage.write_json(pid, 'workflow.json', {'state': 'previewing', 'run': 'walive'})
    w.orchestrator._ACTIVE[key] = object()
    try:
        assert w.status(pid)['state'] == 'previewing'
        assert not storage.read_json(pid, 'workflow.json').get('interrupted')
    finally:
        w.orchestrator._ACTIVE.pop(key)


def test_generated_repair_skips_approved_and_human_mirrors(setup, monkeypatch):
    pid, _, _ = setup
    shots = [{'id': 'S1', 'human_edited': True}, {'id': 'S2', 'review': {'status': 'approved'}}, {'id': 'S3'}]
    storage.write_json(pid, 'shotlist.json', {'shots': shots})
    issues = [{'shot': sid, 'severity': 'block', 'message': '待修复'} for sid in ('S1', 'S2', 'S3')]
    repaired = []
    monkeypatch.setattr(w.planner, 'repair', lambda pid, run, items: repaired.extend(i['shot'] for i in items))
    monkeypatch.setattr(w, '_validated', lambda *args: issues[:2])
    remaining = w._repair_generated(pid, 'test', {}, issues)
    assert repaired == ['S3'] and len(remaining) == 2
