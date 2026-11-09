import io
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from app import config, events, storage
from app.media import compose, tts

REAL_RUN = subprocess.run


def test_render_command_progress_and_limit(project, monkeypatch):
    pid = project["id"]
    storage.write_json(pid, "timeline.json", {"duration_s": 10, "fps": 30})
    monkeypatch.setenv("KEPU_RENDER_MAX_S", "3")
    class Process:
        def __init__(self, args, **kwargs):
            assert args[0] == "node" and args[1] == str(config.ROOT / "web/render/render.mjs")
            assert args[args.index("--url") + 1] == f"http://127.0.0.1:8123/player/index.html?timeline=/files/{pid}/timeline.json&mode=render"
            assert args[-2:] == ["--to", "3.0"]
            Path(args[args.index("--out") + 1]).write_bytes(b"video")
            self.stdout = io.StringIO('无关日志\n' + '\n'.join(json.dumps({"frame": i, "total": 90}) for i in (30, 60, 90)))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def wait(self):
            return 0
    monkeypatch.setattr(compose.subprocess, "Popen", Process)
    assert compose.render_video(pid, "r1", base_url="http://127.0.0.1:8123").is_file()
    history = events.read_events(pid)
    assert history[0]["status"] == "start" and history[-1]["status"] == "ok"
    assert [event["detail"]["progress"] for event in history if "progress" in event["detail"]] == list(range(10, 101, 10))


def test_render_failure_keeps_stderr(project, monkeypatch):
    pid = project["id"]
    storage.write_json(pid, "timeline.json", {"duration_s": 10})
    class Process:
        def __init__(self, args, **kwargs):
            kwargs["stderr"].write("浏览器不可用")
            self.stdout = io.StringIO("")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def wait(self):
            return 1
    monkeypatch.setattr(compose.subprocess, "Popen", Process)
    with pytest.raises(RuntimeError, match="浏览器不可用"):
        compose.render_video(pid, "r1", base_url="http://127.0.0.1:8031")
    assert events.read_events(pid)[-1]["status"] == "error"


@pytest.mark.parametrize("music", [True, False])
def test_mux_command(project, monkeypatch, music):
    pid = project["id"]
    selected = {"file": "renders/music.mp3", "credit": "署名"} if music else None
    storage.write_json(pid, "timeline.json", {"music": selected})
    monkeypatch.setattr(compose, "select_music", lambda pid: None)
    monkeypatch.setattr(compose, "probe_duration", lambda path: 12.5)
    calls = []
    monkeypatch.setattr(compose.subprocess, "run", lambda args, **kw: calls.append(args))
    assert compose.mux(pid, "r1").name == "final.mp4"
    args = calls[0]
    filters = args[args.index("-filter_complex") + 1]
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in filters
    assert ("sidechaincompress" in filters) == music
    if music:
        assert "volume=0.12589254" in filters and "st=10.5:d=2" in filters
        assert "-stream_loop" in args
    assert args[args.index("-b:a") + 1] == "192k"
    assert args[args.index("-t") + 1] == "12.5"
    assert storage.read_json(pid, "timeline.json")["rendered_duration_s"] == 12.5
    assert [e["status"] for e in events.read_events(pid)] == ["start", "ok"]


def local_media_run(args, **kwargs):
    assert Path(args[0]).name in {"ffmpeg", "ffprobe"}, "仅允许本机音视频工具"
    return REAL_RUN(args, **kwargs)


def test_real_fake_tts_timeline_and_mux(project, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("缺少本机音视频工具")
    from app.agent.timeline import build_timeline
    pid, directory = project["id"], storage.project_dir(project["id"])
    monkeypatch.setattr(subprocess, "run", local_media_run)
    monkeypatch.setenv("KEPU_TTS_ENGINE", "fake")
    storage.write_json(pid, "shotlist.json", {"shots": [{"id": "S1", "kind": "title", "source": "graphic",
                       "duration_s": 1, "narration": "测试。", "params": {}}]})
    result = tts.synthesize("测试。", directory / "tts/S1.mp3")
    timeline = build_timeline(pid)
    assert timeline["duration_s"] == pytest.approx(result["duration_s"] + .8)
    assert tts.probe_duration(directory / "renders/narration.wav") == pytest.approx(timeline["duration_s"], abs=.01)
    subprocess.run([tts.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=30",
                    "-t", str(timeline["duration_s"]), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(directory / "renders/video_noaudio.mp4")], check=True, capture_output=True, timeout=60)
    final = compose.mux(pid, "r1")
    assert tts.probe_duration(final) == pytest.approx(timeline["duration_s"], abs=.08)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(final)],
                           check=True, capture_output=True, text=True)
    streams = json.loads(probe.stdout)["streams"]
    assert {s["codec_type"] for s in streams} == {"audio", "video"}
    assert storage.read_json(pid, "timeline.json")["music"]["credit"]
