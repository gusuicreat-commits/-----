"""把已解析分镜和实测配音组装成播放器时间线。"""
from copy import deepcopy
import json
import math
import subprocess

from app import storage
from app.media import tts, compose
from .analogy import REFS, compute
from .text import PLACEHOLDER, format_value, resolve


def references(shot: dict, analogies: dict, rig: dict) -> set[str]:
    params = shot.get("params", {})
    refs = set(shot.get("fact_refs", []))
    refs.update(key for key in PLACEHOLDER.findall(shot.get("narration", "")) if key.startswith("F_"))
    refs.update(params.get("facts", []))
    if params.get("fact"):
        refs.add(params["fact"])
    aids = set(shot.get("analogy_refs", []))
    aids.update(key for key in PLACEHOLDER.findall(shot.get("narration", "")) if key.startswith("A_"))
    aids.add(params.get("analogy"))
    refs.update(analogies[aid]["fact"] for aid in aids if aid in analogies)
    if shot["kind"] == "motion":
        fid = rig.get("axes", {}).get(params.get("axis"), {}).get("speed_fact")
        if fid:
            refs.add(fid)
    return refs


def _badge(shot: dict, model: dict, assets: dict) -> str:
    if shot["source"] == "model":
        return "三维模型渲染 · 依据STEP" if model.get("kind") == "step" else "三维模型渲染 · 参数化重建"
    if shot["source"] == "real":
        aid = shot.get("params", {}).get("asset") or next(iter(shot.get("asset_refs", [])), None)
        return "实拍" if assets.get(aid, {}).get("provenance") == "own" else "参考实拍 · 非本机"
    return "AI 创意画面" if shot["source"] == "ai" else "信息图"


def resolve_analogies(shotlist: dict, facts: dict) -> dict:
    analogies = {a["id"]: deepcopy(a) for a in shotlist.get("analogies", [])}
    for aid, analogy in list(analogies.items()):
        if analogy.get("ref") in REFS and analogy.get("fact") in facts:
            analogies[aid] = compute(aid, facts[analogy["fact"]], analogy["ref"], analogy["axis"])
    return analogies


def build_timeline(pid: str) -> dict:
    directory = storage.project_dir(pid)
    shotlist = storage.read_json(pid, "shotlist.json")
    if not shotlist or not shotlist.get("shots"):
        raise ValueError("尚无可生成时间线的分镜")
    facts = {f["id"]: f for f in storage.read_json(pid, "facts.json", {"facts": []})["facts"]}
    analogies = resolve_analogies(shotlist, facts)
    assets = {a["id"]: {**a, "url": f"/files/{pid}/{a['file']}"}
              for a in storage.read_json(pid, "assets.json", {"assets": []})["assets"]}
    project = storage.read_json(pid, "project.json")
    model = deepcopy(project.get("model") or {})
    rig = storage.read_json(pid, "model/rig.json", {})
    if model:
        model.update(glb=f"/files/{pid}/{model['glb']}", rig=rig)
    timeline = {key: shotlist.get(key, default) for key, default in (("fps", 30), ("width", 1920), ("height", 1080))}
    timeline.update(shots=[], captions=[], facts={}, analogies=analogies, assets=assets, model=model or None,
                    render_mode=project.get("render_mode", "standard"),
                    audio=f"/files/{pid}/renders/narration.wav", music=compose.select_music(pid))
    position, tracks = 0.0, []
    for shot in shotlist["shots"]:
        sid = shot["id"]
        audio = storage.safe_path(directory / "tts", f"{sid}.mp3")
        metadata = json.loads(audio.with_suffix(".words.json").read_text(encoding="utf-8"))
        if isinstance(metadata, list):
            metadata = {"words": metadata, "duration_s": tts.probe_duration(audio)}
        duration = float(metadata["duration_s"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("配音时长无效")
        if project.get("render_mode") == "scale_film":
            from .scale_film import assert_current
            assert_current(pid)
            if duration + .8 > float(shot["duration_s"]):
                raise ValueError(f"镜头 {sid} 实际配音超出尺度短片预算，请缩短台词或明确增加目标时长后重新规划，不裁音")
            end = position + float(shot["duration_s"])
        elif project.get("production_engine"):
            if duration + .8 > float(shot["duration_s"]):
                raise ValueError(f"镜头 {sid} 实际配音超出已预览时长，请缩短台词或调整时长后重新预览")
            end = position + float(shot["duration_s"])
        else:
            end = position + max(float(shot["duration_s"]), duration + .8)
        narration = resolve(shot["narration"], facts, analogies)
        if project.get("render_mode") == "scale_film" and metadata.get("spoken_text") != narration:
            raise ValueError(f"镜头 {sid} 配音与当前台词不匹配，请从tts重跑")
        params = deepcopy(shot.get("params", {}))
        overlays: list[str] = []
        if shot["kind"] == "analogy" and params.get("analogy") in analogies:
            overlays = [analogies[params["analogy"]]["fact"]]
        elif shot["kind"] == "data_card":
            overlays = params.get("facts", [])
        elif shot["kind"] == "weld_macro":
            overlays = [params.get("fact")]
        elif shot["kind"] == "motion":
            axis = rig.get("axes", {}).get(params.get("axis"), {})
            overlays = [axis.get("speed_fact")]
            speed = facts.get(axis.get("speed_fact"), {})
            if speed.get("status") in {"verified", "confirmed"} and speed.get("value", 0) > 0:
                real_s = abs(params["to_m"] - params["from_m"]) * 60 / speed["value"]
                params["speedup"] = max(1, math.ceil(real_s / (end - position)))
        item = {"id": sid, "kind": shot["kind"], "source": shot["source"],
                "badge": _badge(shot, model, assets), "start": position, "end": end,
                "params": params, "narration": narration,
                "text_overlays": [{"text": format_value(facts[fid]["value"], facts[fid]["unit"]), "fact": fid}
                                  for fid in dict.fromkeys(overlays) if fid in facts]}
        timeline["shots"].append(item)
        for caption in tts.make_captions(narration, metadata["words"], position + .35, duration_s=duration):
            if caption["start"] < end:
                timeline["captions"].append({**caption, "end": min(end, caption["end"])})
        timeline["facts"].update({fid: facts[fid] for fid in references(shot, analogies, rig) if fid in facts})
        tracks.append((audio, position + .35))
        position = end
    timeline["duration_s"] = position
    args = [tts.ffmpeg(), "-y", "-v", "error"]
    filters = []
    for index, (audio, start) in enumerate(tracks):
        args += ["-i", str(audio)]
        filters.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=mono,adelay={round(start * 1000)}:all=1[a{index}]")
    inputs = "".join(f"[a{i}]" for i in range(len(tracks)))
    filters.append(f"{inputs}amix=inputs={len(tracks)}:normalize=0,apad,atrim=duration={position}[out]")
    args += ["-filter_complex", ";".join(filters), "-map", "[out]", "-ar", "48000", "-ac", "1",
             "-c:a", "pcm_s16le", "-t", str(position), str(directory / "renders/narration.wav")]
    subprocess.run(args, check=True, capture_output=True, timeout=600)
    storage.write_json(pid, "timeline.json", timeline)
    return timeline


def build_preview(pid: str) -> dict:
    """Silent storyboard preview; never reads TTS files or invokes ffmpeg."""
    shotlist = storage.read_json(pid, "shotlist.json", {})
    if not shotlist.get("shots"):
        raise ValueError("尚无可预览的分镜")
    facts = {f["id"]: f for f in storage.read_json(pid, "facts.json", {"facts": []})["facts"]}
    analogies = resolve_analogies(shotlist, facts)
    project = storage.read_json(pid, "project.json")
    model = deepcopy(project.get("model") or {})
    rig = storage.read_json(pid, "model/rig.json", {})
    if model:
        model.update(glb=f"/files/{pid}/{model['glb']}", rig=rig)
    assets = {a["id"]: {**a, "url": f"/files/{pid}/{a['file']}"} for a in storage.read_json(pid, "assets.json", {"assets": []})["assets"]}
    result = {"fps": shotlist.get("fps", 30), "width": shotlist.get("width", 1920), "height": shotlist.get("height", 1080),
              "shots": [], "captions": [], "facts": facts, "analogies": analogies, "assets": assets,
              "model": model or None, "render_mode": "standard", "audio": None, "music": None, "preview": True}
    position = 0.0
    for shot in shotlist["shots"]:
        end = position + float(shot["duration_s"])
        if not math.isfinite(end) or end <= position:
            raise ValueError("镜头时长必须为有限正数")
        params = deepcopy(shot.get("params", {}))
        narration = resolve(shot["narration"], facts, analogies)
        ids = list(shot.get("fact_refs", []))
        result["shots"].append({"id": shot["id"], "kind": shot["kind"], "source": shot["source"],
                                "badge": _badge(shot, model, assets), "start": position, "end": end,
                                "params": params, "narration": narration,
                                "text_overlays": [{"text": format_value(facts[fid]["value"], facts[fid]["unit"]), "fact": fid}
                                                  for fid in ids if fid in facts]})
        if narration:
            result["captions"].append({"start": position, "end": end, "text": narration})
        position = end
    result["duration_s"] = position
    return result
