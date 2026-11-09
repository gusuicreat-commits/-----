"""固定模型的结构化输出、离线回放与调用留痕。"""
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import anthropic
from app import config, storage

MODEL = "claude-opus-5-5"


class LLMError(Exception):
    pass


def cassette_path(task: str, system: str, user: str, schema: dict, images: list[Path] | tuple = ()) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", task):
        raise LLMError("任务名称包含无效字符")
    content = task + "\0" + system + "\0" + user + "\0" + json.dumps(schema, sort_keys=True)
    content += "".join(hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in images)
    key = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    directory = Path(os.environ.get("KEPU_LLM_CASSETTES", str(config.ROOT / "backend/tests/cassettes")))
    return directory / f"{task}_{key}.json"


def _sdk(system: str, user: str, schema: dict, effort: str, images: list[Path]) -> dict:
    blocks: list[dict] = []
    for path in images:
        media_type = mimetypes.guess_type(path.name)[0]
        if media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            raise LLMError("不支持的图片格式")
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                       "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
    blocks.append({"type": "text", "text": user})
    with anthropic.Anthropic() as client:
        with client.messages.stream(model=MODEL, max_tokens=32000, thinking={"type": "adaptive"},
                                    output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                                    system=system, messages=[{"role": "user", "content": blocks}]) as stream:
            msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise LLMError("大模型拒绝了本次请求")
    for block in msg.content:
        if block.type == "text":
            return json.loads(block.text)
    raise LLMError("大模型未返回文本结果")


def _cli(system: str, user: str, schema: dict, effort: str, images: list[Path]) -> tuple[dict, float | None]:
    args = ["claude", "-p", "--model", MODEL, "--effort", effort, "--system-prompt", system,
            "--output-format", "json", "--json-schema", json.dumps(schema), "--no-session-persistence",
            "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands"]
    if images:
        args += ["--tools", "Read", "--allowedTools", "Read"]
        for directory in dict.fromkeys(str(path.parent) for path in images):
            args += ["--add-dir", directory]
        user = "请先用 Read 工具逐一查看以下图片：\n" + "\n".join(str(path) for path in images) + "\n\n" + user
    else:
        args += ["--tools", ""]
    last_error = ""
    with tempfile.TemporaryDirectory(prefix="kepu-llm-") as cwd:
        for _ in range(2):
            try:
                result = subprocess.run(args, input=user, text=True, capture_output=True, cwd=cwd, timeout=600)
                if result.returncode:
                    raise LLMError("命令行调用失败：" + (result.stderr or result.stdout)[:300])
                payload = json.loads(result.stdout)
                if not isinstance(payload, dict) or payload.get("is_error") or not isinstance(payload.get("structured_output"), dict):
                    reason = payload.get("result", "") if isinstance(payload, dict) else ""
                    raise LLMError("命令行未返回结构化结果：" + str(reason)[:300])
                return payload["structured_output"], payload.get("total_cost_usd")
            except (OSError, subprocess.TimeoutExpired, ValueError, LLMError) as exc:
                last_error = str(exc)
    raise LLMError("大模型命令行调用失败（已重试一次）：" + last_error)


def complete_json(task: str, system: str, user: str, schema: dict, *, pid: str | None = None,
                  effort: str = "high", images: list[Path] = ()) -> dict:
    started = time.monotonic()
    mode = os.environ.get("KEPU_LLM_MODE", "live")
    backend = "replay" if mode == "replay" else "sdk" if (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")) else "cli"
    response: dict | None = None
    cost: float | None = None
    error: str | None = None
    image_paths = [Path(path).resolve() for path in images]
    try:
        if mode not in {"live", "replay", "record"}:
            raise LLMError("大模型模式无效，请使用 live、replay 或 record")
        cassette = cassette_path(task, system, user, schema, image_paths)
        if mode == "replay":
            if not cassette.is_file():
                raise LLMError("缺少录制：" + cassette.name)
            response = json.loads(cassette.read_text(encoding="utf-8"))["response"]
        elif backend == "sdk":
            response = _sdk(system, user, schema, effort, image_paths)
        elif shutil.which("claude"):
            response, cost = _cli(system, user, schema, effort, image_paths)
        else:
            raise LLMError("未配置大模型：请设置 ANTHROPIC_API_KEY 或安装并登录 Claude Code")
        if not isinstance(response, dict):
            raise LLMError("大模型结果必须为 JSON 对象")
        if mode == "record":
            storage.atomic_json(cassette, {"task": task, "system_head": system[:300], "user_head": user[:800], "response": response})
        return response
    except Exception as exc:
        error = str(exc) if isinstance(exc, LLMError) else "大模型调用或结果解析失败：" + str(exc)[:300]
        raise LLMError(error) from exc
    finally:
        if pid is not None and re.fullmatch(r"[A-Za-z0-9_.-]+", task):
            log = {"task": task, "backend": backend, "model": MODEL, "effort": effort,
                   "duration_s": round(time.monotonic() - started, 4), "system_head": system[:300],
                   "user_head": user[:800], "images": [str(path) for path in image_paths], "response": response}
            if cost is not None:
                log["cost_usd"] = cost
            if error is not None:
                log["error"] = error
            with storage.LOCK:
                directory = storage.project_dir(pid) / "llm"
                numbers = [int(path.name.split("_", 1)[0]) for path in directory.glob("*_*.json")
                           if path.name.split("_", 1)[0].isdigit()]
                storage.write_json(pid, f"llm/{max(numbers, default=0) + 1:03d}_{task}.json", log)
