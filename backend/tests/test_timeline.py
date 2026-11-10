import io
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from app import storage
from app.agent import timeline

REAL_RUN = subprocess.run


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


def test_render_limit_preserves_full_preview(project, monkeypatch):
    pid, calls = setup_timeline(project, monkeypatch)
    monkeypatch.setenv("KEPU_RENDER_MAX_S", "4")
    result = timeline.build_timeline(pid)
    assert result["duration_s"] == 28 and len(result["shots"]) == 7
    assert result["shots"][2]["start"] == 8
    assert result["shots"][-1]["end"] == 28
    assert len(result["captions"]) == 7
    assert result["captions"][-1]["start"] == 24.35
    assert "atrim=duration=28.0" in calls[0][calls[0].index("-filter_complex") + 1]
    assert calls[0][calls[0].index("-t") + 1] == "28.0"


def test_timeline_no_shots(project):
    with pytest.raises(ValueError, match="分镜"):
        timeline.build_timeline(project["id"])


def test_full_preview_with_short_render_and_audio(project: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("缺少本机音视频工具")
    pid, directory = project["id"], storage.project_dir(project["id"])
    monkeypatch.setenv("KEPU_RENDER_MAX_S", "4")
    monkeypatch.setenv("KEPU_TTS_ENGINE", "fake")
    monkeypatch.setattr(timeline.compose, "select_music", lambda pid: None)

    def local_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert Path(args[0]).name in {"ffmpeg", "ffprobe"}, "仅允许本机音视频工具"
        return REAL_RUN(args, **kwargs)

    class LocalFrames:
        """用本地纯色帧替代浏览器，仅核验渲染命令和音视频裁剪。"""
        def __init__(self, args: list[str], **kwargs: object) -> None:
            assert args[args.index("--to") + 1] == "4.0"
            local_run([timeline.tts.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                       "color=c=black:s=64x64:r=30", "-t", args[args.index("--to") + 1],
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", args[args.index("--out") + 1]],
                      check=True, capture_output=True, timeout=60)
            self.stdout = io.StringIO('{"frame":120,"total":120}\n')

        def __enter__(self) -> "LocalFrames":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "run", local_run)
    shots = [{"id": f"S{i}", "kind": "title", "source": "graphic", "duration_s": 4,
              "narration": "测试。", "params": {}} for i in range(1, 4)]
    storage.write_json(pid, "shotlist.json", {"shots": shots})
    for shot in shots:
        timeline.tts.synthesize(shot["narration"], directory / "tts" / f"{shot['id']}.mp3")
    result = timeline.build_timeline(pid)
    assert len(result["shots"]) == len(result["captions"]) == 3
    assert result["duration_s"] == 12
    assert timeline.tts.probe_duration(directory / "renders/narration.wav") == pytest.approx(12, abs=.01)
    # 不替换音视频工具内部使用的进程，仅替换渲染入口。
    from types import SimpleNamespace
    monkeypatch.setattr(timeline.compose, "subprocess", SimpleNamespace(
        Popen=LocalFrames, PIPE=subprocess.PIPE, run=local_run))
    video = timeline.compose.render_video(pid, "r1", base_url="http://127.0.0.1:8031")
    final = timeline.compose.mux(pid, "r1")
    for output in (video, final):
        assert timeline.tts.probe_duration(output) == pytest.approx(4, abs=.08)
    probe = local_run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(final)],
                      check=True, capture_output=True, text=True)
    streams = json.loads(probe.stdout)["streams"]
    assert {stream["codec_type"] for stream in streams} == {"audio", "video"}
    for stream in streams:
        assert float(stream["duration"]) == pytest.approx(4, abs=.08)
    saved = storage.read_json(pid, "timeline.json")
    assert saved["duration_s"] == 12 and saved["rendered_duration_s"] == pytest.approx(4, abs=.08)
    assert saved["shots"][2]["start"] == 8


@pytest.mark.parametrize('mode', ['standard','photoreal'])
def test_render_mode_persisted_for_player(project,monkeypatch,mode):
    pid,_ = setup_timeline(project,monkeypatch)
    settings = storage.read_json(pid,'project.json')
    if mode == 'photoreal':
        storage.write_json(pid,'project.json',{**settings,'render_mode':mode})
    result = timeline.build_timeline(pid)
    assert result['render_mode'] == mode
    assert storage.read_json(pid,'timeline.json')['render_mode'] == mode
