"""抽取代表帧并进行画面质检，质检失败不阻断成片。"""
import json
import subprocess
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from app import config, llm, storage
from app.events import emit
from app.media.compose import player_url

SYSTEM = """你是工业科普视频画面质检员。图片按给定镜头顺序排列，逐镜头返回 id、ok 和 problems。
检查：主体是否完整入镜；文字是否重叠或被裁切；字幕是否遮挡主体；来源角标是否可见；
ai_broll 中是否出现起重机（出现即问题）；画面是否空白、穿模，是否符合预期画面要点。
只判断实际可见内容，不臆测不可见细节。问题用简体中文描述，没有问题时 problems 为空。"""


class ShotResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    ok: bool
    problems: list[str]


class QAResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    shots: list[ShotResult]


SCHEMA = QAResult.model_json_schema()


def append_warning(pid: str, message: str, shot: str | None = None) -> None:
    with storage.LOCK:
        data = storage.read_json(pid, "issues.json", {"issues": []})
        used = {item["id"] for item in data["issues"]}
        number = 1
        while f"I{number}" in used:
            number += 1
        data["issues"].append({"id": f"I{number}", "shot": shot, "severity": "warn", "code": "VISUAL_QA",
                               "message": message, "hint": "请人工核对该镜头画面"})
        storage.write_json(pid, "issues.json", data)


def visual_qa(pid: str, run: str, *, base_url: str) -> dict:
    # 每轮只保留本轮画面问题，其他阶段的问题原样保留。
    with storage.LOCK:
        data = storage.read_json(pid, "issues.json", {"issues": []})
        data["issues"] = [item for item in data["issues"] if item.get("code") != "VISUAL_QA"]
        storage.write_json(pid, "issues.json", data)
    args = dict(run=run, stage="qa", tool="llm.opus.visual_qa")
    emit(pid, **args, status="start", summary="正在抽帧并检查画面")
    result: dict = {"shots": []}
    try:
        directory = storage.project_dir(pid)
        shots = storage.read_json(pid, "timeline.json")["shots"]
        target = directory / "renders/frames_qa"
        target.mkdir(parents=True, exist_ok=True)
        for shot in shots:
            storage.safe_path(target, f"{shot['id']}.png").unlink(missing_ok=True)
        times = [shot["start"] + .6 * (shot["end"] - shot["start"]) for shot in shots]
        if storage.read_json(pid, "project.json").get("render_mode") == "scale_film":
            from app.media.tts import ffmpeg
            video = directory / "renders/final.mp4"
            if not video.is_file():
                raise ValueError("尺度短片最终视频不存在，不能质检旧播放器")
            for shot, at in zip(shots, times):
                subprocess.run([ffmpeg(), "-y", "-v", "error", "-ss", str(at), "-i", str(video),
                                "-frames:v", "1", str(storage.safe_path(target, f"{shot['id']}.png"))],
                               check=True, capture_output=True, timeout=60)
        else:
            with tempfile.TemporaryDirectory(dir=directory / "renders", prefix="qa-") as temp:
                subprocess.run(["node", str(config.ROOT / "web/render/render.mjs"), "--url", player_url(pid, base_url),
                                "--frames-at", ",".join(str(t) for t in times), "--frames-dir", temp],
                               check=True, capture_output=True, timeout=600)
                for index, (shot, at) in enumerate(zip(shots, times), 1):
                    source = Path(temp) / f"frame-{index:03d}-{at:.3f}.png"
                    source.replace(storage.safe_path(target, f"{shot['id']}.png"))
        for offset in range(0, len(shots), 10):
            batch = shots[offset:offset + 10]
            prompt = json.dumps([{"id": s["id"], "kind": s["kind"], "source": s["source"],
                                  "台词": s.get("narration", ""), "预期画面要点": s.get("params", {}),
                                  "来源角标": s["badge"], "数值叠加": s.get("text_overlays", [])}
                                 for s in batch], ensure_ascii=False)
            response = QAResult.model_validate(llm.complete_json(
                task="visual_qa", system=SYSTEM, user=prompt, schema=SCHEMA, pid=pid,
                images=[storage.safe_path(target, f"{s['id']}.png") for s in batch]))
            if (len(response.shots) != len(batch)
                    or {s.id for s in response.shots} != {s["id"] for s in batch}):
                raise ValueError("画面质检返回的镜头编号不完整")
            for item in response.shots:
                result["shots"].append(item.model_dump())
                problems = item.problems or ([] if item.ok else ["画面未通过质检，未给出具体原因"])
                for problem in problems:
                    append_warning(pid, problem, item.id)
        warnings = sum(not item["ok"] or bool(item["problems"]) for item in result["shots"])
        emit(pid, **args, status="warn" if warnings else "ok",
             summary=f"画面质检完成：{len(shots)} 个镜头，{warnings} 个需要复核")
    except Exception as exc:
        append_warning(pid, "自动画面质检未完成：" + str(exc)[:500])
        emit(pid, **args, status="warn", summary="自动画面质检未完成，请人工复核成片",
             detail={"error": str(exc)})
        result["error"] = str(exc)
    return result
