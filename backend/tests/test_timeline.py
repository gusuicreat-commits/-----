import pytest
from app import storage
from app.agent import timeline


def setup_timeline(project, monkeypatch, kind="parametric"):
    pid = project["id"]
    project["model"] = {"kind": kind, "glb": "model/crane.glb"}
    storage.write_json(pid, "project.json", project)
    facts = [{"id": "F_girder_length", "name": "主梁长度", "value": 104, "unit": "m", "status": "verified"},
             {"id": "F_trolley_speed", "name": "小车速度", "value": 60, "unit": "m/min", "status": "verified"},
             {"id": "F_unused", "name": "无关参数", "value": 1, "unit": "m", "status": "verified"}]
    storage.write_json(pid, "facts.json", {"facts": facts})
    storage.write_json(pid, "model/rig.json", {"axes": {"trolley": {"speed_fact": "F_trolley_speed"}}})
    storage.write_json(pid, "assets.json", {"assets": [
        {"id": "own", "file": "assets/a.png", "kind": "image", "provenance": "own", "credit": "自有"},
        {"id": "ref", "file": "assets/b.png", "kind": "image", "provenance": "reference", "credit": "参考署名"}]})
    shots = []
    for i, (kind_, source, params) in enumerate([
        ("analogy", "model", {"analogy": "A_length"}), ("real_media", "real", {"asset": "own"}),
        ("real_media", "real", {"asset": "ref"}), ("data_card", "graphic", {"facts": ["F_girder_length"]}),
        ("motion", "model", {"axis": "trolley", "from_m": 0, "to_m": 20}),
        ("weld_macro", "model", {"fact": "F_girder_length"}), ("ai_broll", "ai", {})], 1):
        shots.append({"id": f"S{i}", "kind": kind_, "source": source, "params": params,
                      "narration": "看主梁。", "duration_s": 2, "fact_refs": [], "analogy_refs": [], "asset_refs": []})
        storage.write_json(pid, f"tts/S{i}.words.json", {"duration_s": 3.2, "words": [], "engine": "fake"})
    storage.write_json(pid, "shotlist.json", {"shots": shots, "analogies": [
        {"id": "A_length", "fact": "F_girder_length", "ref": "football_field", "axis": "length"}]})
    monkeypatch.setattr(timeline.compose, "select_music", lambda pid: None)
    calls = []
    monkeypatch.setattr(timeline.subprocess, "run", lambda args, **kw: calls.append(args))
    return pid, calls


@pytest.mark.parametrize("model_kind,badge", [("parametric", "参数化重建"), ("step", "依据STEP")])
def test_timeline_duration_badges_and_facts(project, monkeypatch, model_kind, badge):
    pid, calls = setup_timeline(project, monkeypatch, model_kind)
    result = timeline.build_timeline(pid)
    assert result["duration_s"] == 28
    assert result["shots"][0]["badge"] == "三维模型渲染 · " + badge
    assert [s["badge"] for s in result["shots"]][1:4] == ["实拍", "参考实拍 · 非本机", "信息图"]
    assert result["shots"][-1]["badge"] == "AI 创意画面"
    assert set(result["facts"]) == {"F_girder_length", "F_trolley_speed"}
    assert result["analogies"]["A_length"]["ref_size_m"] == 105
    assert result["model"]["glb"] == f"/files/{pid}/model/crane.glb"
    assert result["assets"]["ref"]["credit"] == "参考署名"
    assert result["shots"][4]["text_overlays"] == [{"text": "每分钟60米", "fact": "F_trolley_speed"}]
    assert result["shots"][4]["params"]["speedup"] == 5
    assert result["captions"][0]["start"] == .35
    assert result["captions"][1]["start"] == 4.35
    filters = calls[0][calls[0].index("-filter_complex") + 1]
    assert "adelay=350" in filters and "adelay=4350" in filters and "normalize=0" in filters
    assert "atrim=duration=28.0" in filters and calls[0][-1].endswith("narration.wav")


def test_timeline_truncates_audio_captions_and_shots(project, monkeypatch):
    pid, calls = setup_timeline(project, monkeypatch)
    monkeypatch.setenv("KEPU_RENDER_MAX_S", "3")
    result = timeline.build_timeline(pid)
    assert result["duration_s"] == 3 and len(result["shots"]) == 1
    assert result["shots"][0]["end"] == 3
    assert all(c["end"] <= 3 for c in result["captions"])
    assert "atrim=duration=3.0" in calls[0][calls[0].index("-filter_complex") + 1]


def test_timeline_no_shots(project):
    with pytest.raises(ValueError, match="分镜"):
        timeline.build_timeline(project["id"])
