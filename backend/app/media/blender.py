"""按镜头缓存写实背景；渲染失败保留网页三维路径。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from app import config, events, storage

MODEL_KINDS = {"title", "model_orbit", "motion", "exploded", "data_card", "outro", "analogy"}
ANALOGY_REFS = {"building_floor", "football_field"}
FACT_IDS = {"F_girder_length", "F_overall_height", "F_span", "F_lift_height",
            "F_girder_height", "F_wheel_count"}


# 对应 web/player/style.css 的 1920×1080 HUD：数字卡 right:70/max-width:500、
# 倍速框 right:75/bottom:265、章节标题 top:154、字幕 bottom:96。
# 安全框按任务规定的 HUD 分区比例，随背景分辨率等比缩放。
HUD_SIDE_MARGIN = .05
HUD_RIGHT_LIMIT = .74
HUD_SECTION_TOP = .20
HUD_CAPTION_BOTTOM = .86
# 左侧参数卡及片尾左上标题的独立留白；这两类不显示右侧数字卡。
HUD_DATA_LEFT = .46
HUD_OUTRO_LEFT = .40
HUD_OUTRO_TOP = .30


def shot_safe_rect(shot: dict) -> tuple[float, float, float, float]:
    kind = shot["kind"]
    if kind == "analogy":
        return (.08,.23,.92,.80)
    if kind in {"data_card", "outro"}:
        return (HUD_DATA_LEFT if kind == "data_card" else HUD_OUTRO_LEFT,
                HUD_SIDE_MARGIN if kind == "data_card" else HUD_OUTRO_TOP,
                1-HUD_SIDE_MARGIN, .80 if kind == "outro" else HUD_CAPTION_BOTTOM)
    return (.45 if kind == "title" else HUD_SIDE_MARGIN,
            HUD_SECTION_TOP if kind in {"model_orbit", "motion", "exploded"} else HUD_SIDE_MARGIN,
            HUD_RIGHT_LIMIT if shot.get("text_overlays") or kind == "motion" else 1-HUD_SIDE_MARGIN,
            HUD_CAPTION_BOTTOM)


def blender_executable() -> str | None:
    configured = os.environ.get("KEPU_BLENDER")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return shutil.which(configured)
    default = Path("/Applications/Blender.app/Contents/MacOS/Blender")
    if default.is_file() and os.access(default, os.X_OK):
        return str(default)
    return shutil.which("blender")


def cache_key(shot: dict, facts: dict, engine: str, width: int, height: int, fps: int, look: str = "afternoon") -> str:
    digest = hashlib.sha256()
    for path in sorted((config.ROOT / "blender").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    # 尺寸默认值由共享规则派生，同样参与失效判断。
    digest.update((config.ROOT / "backend/app/model3d/rig.py").read_bytes())
    accepted = {item["id"]: item["value"] for item in facts.get("facts", [])
                if item["id"] in FACT_IDS and item.get("status") in {"verified", "confirmed"}}
    payload = {"kind": shot["kind"], "params": shot.get("params", {}),
               "duration": shot["end"] - shot["start"], "facts": accepted,
               "engine": engine, "width": width, "height": height, "fps": fps,
               "safe_rect": shot_safe_rect(shot), "look": look,
               "analogy_data": shot.get("analogy_data")}
    digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())
    return digest.hexdigest()[:12]


def parse_progress(line: str) -> tuple[int, int] | None:
    match = re.search(r"已完成第\s+(\d+)/(\d+)\s+帧", line)
    if match:
        frame, total = map(int, match.groups())
        if 0 < frame <= total:
            return frame, total
    return None


def _render(args: list[str], timeout: float, on_line: Callable[[str], None]) -> None:
    # 独立读取输出，主线程用截止时间限制静默、启动和测光阶段。
    lines: queue.Queue[str | None] = queue.Queue()
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace", cwd=config.ROOT) as process:
        def read() -> None:
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        tail: list[str] = []
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("写实渲染超时")
                try:
                    line = lines.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError("写实渲染超时") from exc
                if line is None:
                    break
                tail = (tail + [line])[-20:]
                on_line(line)
            code = process.wait(timeout=max(.001, deadline - time.monotonic()))
            if code:
                raise RuntimeError("写实渲染失败：" + "".join(tail)[-2000:])
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            reader.join(timeout=2)


def render_model_shots(pid: str, run: str, timeline: dict) -> dict[str, dict]:
    project = storage.read_json(pid, "project.json", {})
    if project.get("render_mode", "standard") != "photoreal":
        return {}
    executable = blender_executable()
    if not executable:
        events.emit(pid, run=run, stage="render", tool="render.blender", status="warn",
                    summary="未找到 Blender，写实镜头已整体回退网页三维")
        return {}
    result: dict[str, dict] = {}
    directory = storage.project_dir(pid)
    facts = storage.read_json(pid, "facts.json", {"facts": []})
    engine = os.environ.get("KEPU_BLENDER_ENGINE", "eevee")
    preview = os.environ.get("KEPU_BLENDER_PREVIEW") == "1"
    width, height = (960, 540) if preview else (1920, 1080)
    fps = int(timeline.get("fps", 30))
    look = os.environ.get("KEPU_BLENDER_LOOK", "afternoon")
    for original in timeline["shots"]:
        shot = dict(original)
        if shot["kind"] == "analogy":
            analogy = timeline.get("analogies", {}).get(shot.get("params", {}).get("analogy"), {})
            if analogy.get("ref") not in ANALOGY_REFS:
                continue
            shot["analogy_data"] = dict(analogy)
        if shot["kind"] not in MODEL_KINDS:
            continue
        sid = shot["id"]
        events.emit(pid, run=run, stage="render", tool="render.blender", status="start",
                    summary=f"正在写实渲染镜头 {sid}", detail={"shot": sid})
        try:
            if look not in {"afternoon", "dusk"}:
                raise ValueError("写实画面风格无效")
            if engine not in {"eevee", "cycles"}:
                raise ValueError("写实渲染引擎无效")
            timeout = float(os.environ.get("KEPU_BLENDER_TIMEOUT_S", "1800"))
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("写实渲染时限必须是有限正数")
            duration = shot["end"] - shot["start"]
            count = math.ceil(duration * fps)
            if count <= 0 or fps <= 0:
                raise ValueError("镜头时长和帧率必须大于零")
            name = f"{sid}-{cache_key(shot, facts, engine, width, height, fps, look)}"
            out = storage.safe_path(directory / "renders/blender", name)
            out.mkdir(parents=True, exist_ok=True)
            done = out / "done.json"
            if not done.is_file():
                started = time.monotonic()
                last = 0
                def progress(line: str) -> None:
                    nonlocal last
                    parsed = parse_progress(line)
                    if parsed is None:
                        return
                    frame, total = parsed
                    if frame - last >= 30 or frame == total:
                        last = frame
                        events.emit(pid, run=run, stage="render", tool="render.blender", status="start",
                                    summary=f"镜头 {sid} 写实渲染已完成 {frame}/{total} 帧",
                                    detail={"shot": sid, "frame": frame, "total": total,
                                            "progress": round(frame / total * 100, 1)})
                args = [executable, "--background", "--factory-startup", "--python-exit-code", "1", "--python",
                        str(config.ROOT / "blender/render_shot.py"), "--",
                        "--facts", str(directory / "facts.json"), "--shot-json", json.dumps(shot, ensure_ascii=False),
                        "--out", str(out), "--engine", engine, "--look", look, "--fps", str(fps),
                        "--duration", str(duration), "--frame-format", "jpg", "--skip-video",
                        "--safe-rect", ",".join(str(v) for v in shot_safe_rect(shot))]
                if preview:
                    args.append("--preview")
                _render(args, timeout, progress)
                if not (out / "anchors.json").is_file() or any(
                        not (out / f"frame_{i:05d}.jpg").is_file() for i in range(1, count + 1)):
                    raise RuntimeError("写实渲染未生成完整帧和锚点")
                storage.atomic_json(done, {"count": count, "fps": fps, "engine": engine,
                                           "look": look, "seconds": round(time.monotonic() - started, 3)})
            base = f"/files/{pid}/renders/blender/{name}"
            result[sid] = {"frames": base + "/frame_%05d.jpg", "count": count, "fps": fps,
                           "anchors": base + "/anchors.json", "engine": engine,
                           "width": width, "height": height, "look": look}
        except Exception as exc:
            events.emit(pid, run=run, stage="render", tool="render.blender", status="warn",
                        summary=f"镜头 {sid} 写实渲染失败，已回退网页三维",
                        detail={"shot": sid, "error": str(exc)[-2000:]})
        else:
            events.emit(pid, run=run, stage="render", tool="render.blender", status="ok",
                        summary=f"镜头 {sid} 写实背景已就绪", detail={"shot": sid})
    return result
