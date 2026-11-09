import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import subprocess

import pytest
from app import llm, storage

SCHEMA = {"type": "object", "properties": {"值": {"type": "number"}}}


def enable_cli(monkeypatch, runner):
    monkeypatch.setenv("KEPU_LLM_MODE", "live")
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/bin/claude")
    monkeypatch.setattr(llm.subprocess, "run", runner)


def test_cli_flags_and_audit(monkeypatch, project):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert Path(kwargs["cwd"]).is_dir()
        return SimpleNamespace(returncode=0, stdout=json.dumps({"structured_output": {"值": 104}, "total_cost_usd": .12}), stderr="")
    enable_cli(monkeypatch, run)
    assert llm.complete_json("test", "系统", "用户", SCHEMA, pid=project["id"]) == {"值": 104}
    args, kwargs = calls[0]
    for flag, value in {"--model": llm.MODEL, "--effort": "high", "--system-prompt": "系统",
                        "--output-format": "json", "--setting-sources": "", "--tools": ""}.items():
        assert args[args.index(flag) + 1] == value
    assert json.loads(args[args.index("--json-schema") + 1]) == SCHEMA
    assert {"--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"} <= set(args)
    assert kwargs["input"] == "用户" and kwargs["timeout"] == 600
    assert not Path(kwargs["cwd"]).exists()
    log = storage.read_json(project["id"], "llm/001_test.json")
    assert log["backend"] == "cli" and log["cost_usd"] == .12
    assert log["model"] == llm.MODEL and log["response"] == {"值": 104}


def test_cli_images(monkeypatch, tmp_path):
    image = tmp_path / "图.png"
    image.write_bytes(b"image")
    def run(args, **kwargs):
        assert args[args.index("--tools") + 1] == "Read"
        assert args[args.index("--allowedTools") + 1] == "Read"
        assert args[args.index("--add-dir") + 1] == str(tmp_path)
        assert str(image) in kwargs["input"] and kwargs["input"].startswith("请先用 Read")
        return SimpleNamespace(returncode=0, stdout='{"structured_output":{}}', stderr="")
    enable_cli(monkeypatch, run)
    assert llm.complete_json("test", "系统", "用户", {}, images=[image]) == {}


@pytest.mark.parametrize("payload", [{"is_error": True, "result": "失败详情"}, {"result": "缺少结果"}, [], {"structured_output": []}])
def test_cli_retry_failure(monkeypatch, payload):
    runner = MagicMock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""))
    enable_cli(monkeypatch, runner)
    with pytest.raises(llm.LLMError, match="已重试一次"):
        llm.complete_json("test", "", "", {})
    assert runner.call_count == 2


@pytest.mark.parametrize("first", [subprocess.TimeoutExpired("claude", 600), SimpleNamespace(returncode=1, stdout="", stderr="出错"), SimpleNamespace(returncode=0, stdout="broken", stderr="")])
def test_cli_retry_recovers(monkeypatch, first):
    runner = MagicMock(side_effect=[first, SimpleNamespace(returncode=0, stdout='{"structured_output":{}}', stderr="")])
    enable_cli(monkeypatch, runner)
    assert llm.complete_json("test", "", "", {}) == {}
    assert runner.call_count == 2


@pytest.mark.parametrize("credential", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"])
def test_sdk(monkeypatch, tmp_path, project, credential):
    monkeypatch.setenv("KEPU_LLM_MODE", "live")
    monkeypatch.setenv(credential, "test-only")
    constructor = MagicMock()
    client = constructor.return_value.__enter__.return_value
    stream = client.messages.stream.return_value.__enter__.return_value
    stream.get_final_message.return_value = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text='{"值":104}')])
    monkeypatch.setattr(llm.anthropic, "Anthropic", constructor)
    image = tmp_path / "图.png"
    image.write_bytes(b"image")
    assert llm.complete_json("test", "系统", "用户", SCHEMA, images=[image], effort="medium", pid=project["id"]) == {"值": 104}
    kwargs = client.messages.stream.call_args.kwargs
    assert kwargs["model"] == llm.MODEL and kwargs["max_tokens"] == 32000
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert kwargs["system"] == "系统"
    blocks = kwargs["messages"][0]["content"]
    assert blocks[0]["source"] == {"type": "base64", "media_type": "image/png", "data": base64.b64encode(b"image").decode()}
    assert blocks[-1] == {"type": "text", "text": "用户"}
    assert storage.read_json(project["id"], "llm/001_test.json")["backend"] == "sdk"
    stream.get_final_message.return_value.stop_reason = "refusal"
    with pytest.raises(llm.LLMError, match="拒绝"):
        llm.complete_json("test", "", "", {})


def test_record_replay_key_and_missing(monkeypatch, tmp_path, project):
    monkeypatch.setenv("KEPU_LLM_CASSETTES", str(tmp_path / "cassettes"))
    image = tmp_path / "图.png"
    image.write_bytes(b"image")
    runner = MagicMock(return_value=SimpleNamespace(returncode=0, stdout='{"structured_output":{"ok":true}}', stderr=""))
    enable_cli(monkeypatch, runner)
    monkeypatch.setenv("KEPU_LLM_MODE", "record")
    llm.complete_json("test", "系统", "用户", SCHEMA, images=[image], pid=project["id"])
    content = "test\0系统\0用户\0" + json.dumps(SCHEMA, sort_keys=True) + hashlib.sha256(b"image").hexdigest()
    key = hashlib.sha256(content.encode()).hexdigest()[:16]
    cassette = tmp_path / "cassettes" / f"test_{key}.json"
    assert json.loads(cassette.read_text()) == {"task": "test", "system_head": "系统", "user_head": "用户", "response": {"ok": True}}
    monkeypatch.setenv("KEPU_LLM_MODE", "replay")
    assert llm.complete_json("test", "系统", "用户", SCHEMA, images=[image], pid=project["id"]) == {"ok": True}
    assert runner.call_count == 1
    assert storage.read_json(project["id"], "llm/002_test.json")["backend"] == "replay"
    with pytest.raises(llm.LLMError, match="缺少录制：test_"):
        llm.complete_json("test", "另一个", "用户", SCHEMA, pid=project["id"])
    assert storage.read_json(project["id"], "llm/003_test.json")["response"] is None


def test_unconfigured_and_invalid_mode(monkeypatch):
    monkeypatch.setenv("KEPU_LLM_MODE", "live")
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    with pytest.raises(llm.LLMError, match="未配置大模型"):
        llm.complete_json("test", "", "", {})
    monkeypatch.setenv("KEPU_LLM_MODE", "invalid")
    with pytest.raises(llm.LLMError, match="模式无效"):
        llm.complete_json("test", "", "", {})
