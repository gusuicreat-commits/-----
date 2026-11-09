"""配音与按文字位置对齐的字幕。"""
import asyncio
import inspect
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

import edge_tts
from app import storage

ENGINE: Callable | None = None


def ffmpeg() -> str:
    return os.environ.get("FFMPEG", "ffmpeg")


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [os.environ.get("FFPROBE", "ffprobe"), "-v", "error", "-show_entries",
         "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("音视频时长无效")
    return duration


async def _edge(text: str, out_mp3: Path, *, voice: str, rate: str) -> dict:
    kwargs = {"voice": voice, "rate": rate}
    if "boundary" in inspect.signature(edge_tts.Communicate).parameters:
        kwargs["boundary"] = "WordBoundary"
    try:
        communicate = edge_tts.Communicate(text, **kwargs)
    except (TypeError, ValueError):
        kwargs["boundary"] = "SentenceBoundary"
        communicate = edge_tts.Communicate(text, **kwargs)
    words = []
    with out_mp3.open("wb") as out:
        async for item in communicate.stream():
            if item["type"] == "audio":
                out.write(item["data"])
            elif item["type"] in {"WordBoundary", "SentenceBoundary"}:
                start = item["offset"] / 10_000_000
                words.append({"start": start, "end": start + item["duration"] / 10_000_000,
                              "text": item["text"]})
    return {"words": words, "engine": "edge"}


def fake_engine(text: str, out_mp3: Path, **_: str) -> dict:
    duration = max(.22, len(text) * .22)
    subprocess.run([ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=mono", "-t", str(duration), str(out_mp3)],
                   check=True, capture_output=True, timeout=120)
    return {"engine": "fake", "words": [
        {"start": index * .22, "end": (index + 1) * .22, "text": char}
        for index, char in enumerate(text)]}


def _say(text: str, out_mp3: Path) -> dict:
    aiff = out_mp3.with_suffix(".aiff")
    try:
        subprocess.run(["say", "-v", "Tingting", "-o", str(aiff), "--", text],
                       check=True, capture_output=True, timeout=300)
        subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", str(aiff), str(out_mp3)],
                       check=True, capture_output=True, timeout=120)
    finally:
        aiff.unlink(missing_ok=True)
    return {"words": [], "engine": "say"}


def synthesize(text: str, out_mp3: Path, *, voice: str = "zh-CN-YunjianNeural",
               rate: str = "+4%") -> dict:
    out_mp3 = Path(out_mp3)
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    engine = ENGINE or (fake_engine if os.environ.get("KEPU_TTS_ENGINE") == "fake" or not text.strip() else _edge)
    try:
        result = engine(text, out_mp3, voice=voice, rate=rate)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        result = {**result, "duration_s": probe_duration(out_mp3)}
    except Exception:
        # 注入引擎的错误应保留，避免测试意外访问系统配音。
        if engine is not _edge:
            raise
        result = {**_say(text, out_mp3), "duration_s": probe_duration(out_mp3)}
    storage.atomic_json(out_mp3.with_suffix(".words.json"), result["words"])
    return result


def _characters(text: str) -> str:
    return "".join(char for char in text if char.isalnum())


def make_captions(text: str, words: list[dict], offset_s: float,
                  *, duration_s: float | None = None) -> list[dict]:
    parts = [part.strip() for part in re.split(r"[，。！？；：、,!?;:\n]+", text)]
    segments = [part[i:i + 18] for part in parts for i in range(0, len(part), 18)]
    segments = [part for part in segments if _characters(part)]
    if not segments:
        return []
    total = sum(len(_characters(part)) for part in segments)
    timings: list[tuple[float, float]] = []
    for word in words:
        count = len(_characters(word["text"]))
        start, end = float(word["start"]), float(word["end"])
        timings.extend((start + (end - start) * i / count, start + (end - start) * (i + 1) / count)
                       for i in range(count))
    duration = duration_s if duration_s is not None else (max((w["end"] for w in words), default=total * .22))
    captions, position = [], 0
    for part in segments:
        count = len(_characters(part))
        if timings:
            first = min(len(timings) - 1, position * len(timings) // total)
            last = min(len(timings) - 1, max(first, math.ceil((position + count) * len(timings) / total) - 1))
            start, end = timings[first][0], timings[last][1]
        else:
            start, end = duration * position / total, duration * (position + count) / total
        captions.append({"start": offset_s + min(start, duration), "end": offset_s + min(end, duration), "text": part})
        position += count
    return captions
