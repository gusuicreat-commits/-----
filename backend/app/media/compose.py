"""调用播放器逐帧渲染，并混合配音与署名配乐。"""
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from app import config, storage
from app.events import emit, tool_call
from .tts import ffmpeg, probe_duration


def select_music(pid: str) -> dict | None:
    credits = config.ROOT / "samples/music/CREDITS.json"
    if not credits.is_file():
        return None
    items = json.loads(credits.read_text(encoding="utf-8"))
    item = next((item for item in items if item.get("default")), None)
    if item is None:
        return None
    source = storage.safe_path(credits.parent, item["file"])
    target = storage.project_dir(pid) / "renders" / ("music" + source.suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return {**item, "file": str(target.relative_to(storage.project_dir(pid))),
            "url": f"/files/{pid}/renders/{target.name}",
            "credit": " / ".join(item.get(key, "") for key in ("author", "license", "source"))}


def player_url(pid: str, base_url: str) -> str:
    return base_url.rstrip("/") + "/player/index.html?" + urlencode(
        {"timeline": f"/files/{pid}/timeline.json", "mode": "render"}, safe="/")


def render_video(pid: str, run: str, *, base_url: str) -> Path:
    out = storage.project_dir(pid) / "renders/video_noaudio.mp4"
    timeline = storage.read_json(pid, "timeline.json")
    args = ["node", str(config.ROOT / "web/render/render.mjs"), "--url", player_url(pid, base_url),
            "--out", str(out), "--fps", str(timeline.get("fps", 30))]
    if os.environ.get("KEPU_RENDER_MAX_S"):
        maximum = float(os.environ["KEPU_RENDER_MAX_S"])
        if not math.isfinite(maximum) or maximum <= 0:
            raise ValueError("渲染截断时长必须大于零")
        args += ["--to", str(min(maximum, timeline["duration_s"]))]
    with tool_call(pid, run, "render", "render.player", "正在逐帧渲染画面") as call:
        # 错误流落入临时文件，避免管道填满后与进度读取互锁。
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors, text=True, cwd=config.ROOT) as process:
                last = 0
                for line in process.stdout:
                    try:
                        progress = json.loads(line)
                        percentage = (100 * float(progress["frame"]) / float(progress["total"])
                                      if progress.get("total") else 100.0 if progress.get("done") else float(progress.get("progress", 0)))
                    except (ValueError, TypeError, KeyError):
                        continue
                    bucket = min(100, int(percentage // 10) * 10)
                    while last < bucket:
                        last += 10
                        emit(pid, run=run, stage="render", tool="render.player", status="start",
                             summary=f"画面渲染完成 {last}%", detail={"progress": last})
                code = process.wait()
                if code:
                    errors.seek(0)
                    raise RuntimeError("画面渲染失败：" + errors.read()[-2000:])
        if not out.is_file():
            raise RuntimeError("画面渲染未生成视频文件")
        call.ok("画面渲染完成")
    return out


def mux(pid: str, run: str) -> Path:
    directory = storage.project_dir(pid)
    timeline = storage.read_json(pid, "timeline.json")
    video, narration = directory / "renders/video_noaudio.mp4", directory / "renders/narration.wav"
    out = directory / "renders/final.mp4"
    with tool_call(pid, run, "compose", "ffmpeg.compose", "正在混合配音、配乐并统一响度") as call:
        duration = probe_duration(video)
        music = timeline.get("music")
        if music is None:
            music = select_music(pid)
            timeline["music"] = music
        args = [ffmpeg(), "-y", "-v", "error", "-i", str(video), "-i", str(narration)]
        if music:
            music_path = storage.safe_path(directory, music["file"])
            args += ["-stream_loop", "-1", "-i", str(music_path)]
            filters = (
                f"[1:a]apad,atrim=duration={duration},asplit=2[voice][side];"
                f"[2:a]atrim=duration={duration},asetpts=PTS-STARTPTS,volume=0.12589254,"
                f"afade=t=in:st=0:d=1,afade=t=out:st={max(0, duration - 2)}:d=2[music];"
                "[music][side]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=350[duck];"
                "[voice][duck]amix=inputs=2:duration=first:normalize=0,"
                "loudnorm=I=-16:TP=-1.5:LRA=11[audio]"
            )
        else:
            filters = f"[1:a]apad,atrim=duration={duration},loudnorm=I=-16:TP=-1.5:LRA=11[audio]"
        args += ["-filter_complex", filters, "-map", "0:v:0", "-map", "[audio]", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", str(duration),
                 "-movflags", "+faststart", str(out)]
        subprocess.run(args, check=True, capture_output=True, timeout=600)
        timeline["rendered_duration_s"] = duration
        storage.write_json(pid, "timeline.json", timeline)
        call.ok("成片已生成，配乐署名已保存")
    return out
