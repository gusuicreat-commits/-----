"""质检重跑以本轮回放结果替换旧问题，保留其他来源的问题。"""
import json
from pathlib import Path

import pytest

from app import llm, storage
from app.agent import qa, validator


@pytest.mark.parametrize("second_problems", [["本轮标签间距不足", "本轮尺寸线错位"], []])
def test_qa_rerun_replaces_previous_cassette_issues(
    project: dict, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, second_problems: list[str]
) -> None:
    pid = project["id"]
    monkeypatch.setenv("KEPU_LLM_CASSETTES", str(tmp_path / "cassettes"))
    shot = {"id": "S1", "kind": "exploded", "source": "model", "start": 0, "end": 5,
            "badge": "三维模型渲染 · 参数化重建", "params": {}}
    storage.write_json(pid, "timeline.json", {"shots": [shot]})
    retained = {"id": "I1", "shot": "S1", "severity": "warn", "code": "UNSOURCED_NUMBER",
                "message": "保留校验问题", "hint": "人工核对"}
    storage.write_json(pid, "issues.json", {"issues": [retained]})
    prompt = json.dumps([{"id": "S1", "kind": "exploded", "source": "model", "台词": "",
                          "预期画面要点": {}, "来源角标": shot["badge"], "数值叠加": []}], ensure_ascii=False)
    rounds = iter([(["旧轮穿模", "旧轮重叠"], b"first-frame"), (second_problems, b"second-frame")])

    def render(args: list[str], **kwargs: object) -> None:
        problems, frame = next(rounds)
        output = Path(args[args.index("--frames-dir") + 1]) / "frame-001-3.000.png"
        output.write_bytes(frame)
        cassette = llm.cassette_path("visual_qa", qa.SYSTEM, prompt, qa.SCHEMA, [output])
        storage.atomic_json(cassette, {"response": {"shots": [
            {"id": "S1", "ok": not problems, "problems": problems}]}})

    monkeypatch.setattr(qa.subprocess, "run", render)
    for run, expected in [("r1", ["旧轮穿模", "旧轮重叠"]), ("r2", second_problems)]:
        result = qa.visual_qa(pid, run, base_url="http://127.0.0.1:8031")
        assert "error" not in result
        issues = storage.read_json(pid, "issues.json")["issues"]
        assert [item for item in issues if item["code"] != "VISUAL_QA"] == [retained]
        assert [item["message"] for item in issues if item["code"] == "VISUAL_QA"] == expected
        assert len({item["id"] for item in issues}) == len(issues)
    logs = sorted((storage.project_dir(pid) / "llm").glob("*_visual_qa.json"))
    assert len(logs) == 2
    assert all(json.loads(path.read_text())["backend"] == "replay" for path in logs)
    assert len(list((tmp_path / "cassettes").glob("*.json"))) == 2


def test_qa_failed_rerun_discards_stale_findings(project: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = project["id"]
    qa.append_warning(pid, "旧轮画面问题", "S1")
    storage.write_json(pid, "timeline.json", {"shots": []})

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("本轮抽帧失败")

    monkeypatch.setattr(qa.subprocess, "run", fail)
    result = qa.visual_qa(pid, "r2", base_url="http://127.0.0.1:8031")
    issues = storage.read_json(pid, "issues.json")["issues"]
    assert result["error"] == "本轮抽帧失败"
    assert len(issues) == 1 and "本轮抽帧失败" in issues[0]["message"]


def test_validate_rerun_replaces_previous_issues(project: dict) -> None:
    pid = project["id"]
    storage.write_json(pid, "shotlist.json", {"shots": [], "analogies": []})
    expected = validator.validate(pid, "r1")
    storage.write_json(pid, "issues.json", {"issues": [{"id": "I99", "code": "UNSOURCED_NUMBER",
                                                       "message": "上一轮的问题"}]})
    assert validator.validate(pid, "r2") == expected
    assert storage.read_json(pid, "issues.json") == expected
