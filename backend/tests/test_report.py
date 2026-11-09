import json
from pathlib import Path

from app import events, llm, storage
from app.agent import qa, report


def test_report_provenance_costs_and_escaping(project):
    pid = project["id"]
    project["name"] = '<script>alert("测试")</script>'
    project["model"] = {"kind": "parametric", "glb": "model/crane.glb", "derived_from": ["F_span"],
                        "assumed": ["F_girder_height"], "dims_check": [{"fact": "F_span", "ok": False,
                        "model_value": 90, "doc_value": 88, "message": "尺寸不一致"}]}
    storage.write_json(pid, "project.json", project)
    fact = {"id": "F_span", "name": "跨度", "value": 88, "unit": "m", "status": "confirmed",
            "source": {"doc": "技术文档.pdf", "page": 2, "quote": "跨度88米"}}
    analogy = {"id": "A_span", "fact": "F_span", "text": "很宽", "formula": "88 ÷ 12 ≈ 7.33", "basis": "公交车长12米"}
    shot = {"id": "S1", "kind": "real_media", "source": "real", "badge": "参考实拍 · 非本机", "start": 0, "end": 4,
            "params": {"asset": "IMG_1"}, "narration": "跨度88米，很宽。"}
    original = {**shot, "narration": "跨度{{F_span}}，{{A_span}}。<script>坏</script>",
                "fact_refs": ["F_span"], "analogy_refs": ["A_span"], "review": {"status": "changes", "note": "需调整"}}
    asset = {"id": "IMG_1", "credit": "摄影者 / 许可 / 来源", "title": "参考实拍", "provenance": "reference"}
    storage.write_json(pid, "shotlist.json", {"shots": [original]})
    storage.write_json(pid, "timeline.json", {"duration_s": 4, "shots": [shot], "facts": {"F_span": fact},
                       "analogies": {"A_span": analogy}, "assets": {"IMG_1": asset},
                       "music": {"title": "配乐", "credit": "配乐作者"}})
    issue = {"id": "I1", "shot": "S1", "severity": "block", "code": "TEST", "message": "待处理问题"}
    storage.write_json(pid, "issues.json", {"issues": [issue]})
    storage.write_json(pid, "run.json", {"run": "r1", "forced": True, "stage_durations_s": {"tts": 1.2}})
    storage.write_json(pid, "llm/001_plan.json", {"cost_usd": .12})
    storage.write_json(pid, "llm/002_qa.json", {"backend": "replay"})
    frame = storage.project_dir(pid) / "renders/frames_qa/S1.png"
    frame.parent.mkdir()
    frame.write_bytes(b"test-png")
    result = report.build_report(pid)
    assert result["runtime_model"] == "claude-opus-5-5"
    assert result["llm"] == {"calls": 2, "cost_usd": .12, "unknown_cost_calls": 1, "scope": "项目全部调用"}
    assert result["facts"][0]["status_label"] == "人工确认"
    assert result["shots"][0]["assets"] == [asset]
    assert result["shots"][0]["thumbnail"].startswith("data:image/png;base64,")
    assert result["issues_by_severity"]["block"] == [issue]
    assert storage.read_json(pid, "report.json") == result
    html = (storage.project_dir(pid) / "report.html").read_text()
    assert "<script>" not in html and "&lt;script&gt;" in html
    for text in ("存在未处理的阻断问题", "强制继续", "参数来源", "镜头溯源", "三维模型", "问题清单", "素材与配乐署名",
                 "技术文档.pdf 第2页", "<mark", "配乐作者", "需调整", "未提供费用", "@media print"):
        assert text in html
    assert events.read_events(pid)[-1]["tool"] == "report.provenance"


def qa_timeline(pid, count):
    shots = [{"id": f"S{i}", "kind": "ai_broll", "source": "ai", "badge": "AI 创意画面", "start": i * 2,
              "end": i * 2 + 2, "narration": "观察光线", "params": {"recipe": "sunrise_port"}} for i in range(count)]
    storage.write_json(pid, "timeline.json", {"shots": shots})
    return shots


def fake_frames(args, **kwargs):
    target = Path(args[args.index("--frames-dir") + 1])
    times = [float(t) for t in args[args.index("--frames-at") + 1].split(",")]
    for index, at in enumerate(times, 1):
        (target / f"frame-{index:03d}-{at:.3f}.png").write_bytes(b"frame")


def test_qa_batches_images_and_preserves_issues(project, monkeypatch):
    pid = project["id"]
    qa_timeline(pid, 11)
    original = {"id": "I1", "severity": "block", "message": "原问题"}
    storage.write_json(pid, "issues.json", {"issues": [original]})
    monkeypatch.setattr(qa.subprocess, "run", fake_frames)
    sizes = []
    replay = llm.complete_json
    def complete(**kwargs):
        sizes.append(len(kwargs["images"]))
        assert kwargs["task"] == "visual_qa"
        assert all(p.is_file() for p in kwargs["images"])
        return replay(**kwargs)
    monkeypatch.setattr(llm, "complete_json", complete)
    assert len(qa.visual_qa(pid, "r1", base_url="http://127.0.0.1:8031")["shots"]) == 11
    assert sizes == [10, 1]
    issues = storage.read_json(pid, "issues.json")["issues"]
    assert issues[0] == original and issues[1]["code"] == "VISUAL_QA" and issues[1]["severity"] == "warn"
    assert (storage.project_dir(pid) / "renders/frames_qa/S10.png").is_file()
    assert not list((storage.project_dir(pid) / "renders").glob("qa-*"))


def test_qa_failure_is_warning(project, monkeypatch):
    pid = project["id"]
    qa_timeline(pid, 1)
    monkeypatch.setattr(qa.subprocess, "run", fake_frames)
    monkeypatch.setattr(llm, "complete_json", lambda **kw: {"shots": []})
    result = qa.visual_qa(pid, "r1", base_url="http://127.0.0.1:8031")
    assert "error" in result
    assert events.read_events(pid)[-1]["status"] == "warn"
    assert storage.read_json(pid, "issues.json")["issues"][0]["code"] == "VISUAL_QA"
