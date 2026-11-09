"""可跨线程发布的进程内事件流。"""
import asyncio
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import RLock
from typing import Iterator

from app.storage import project_dir

_LOCK = RLock()
_SUBSCRIBERS: dict[str, dict[asyncio.Queue, asyncio.AbstractEventLoop]] = {}


def emit(pid: str, *, run: str, stage: str, tool: str, status: str,
         summary: str, detail: dict | None = None) -> dict:
    event = {"ts": datetime.now(timezone.utc).isoformat(), "run": run, "stage": stage,
             "tool": tool, "status": status, "summary": summary, "detail": detail or {}}
    with _LOCK:
        with (project_dir(pid) / "events.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(event, ensure_ascii=False) + "\n")
        for queue, loop in list(_SUBSCRIBERS.get(pid, {}).items()):
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                _SUBSCRIBERS[pid].pop(queue, None)
    return event


def subscribe(pid: str) -> asyncio.Queue:
    project_dir(pid)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    with _LOCK:
        _SUBSCRIBERS.setdefault(pid, {})[queue] = loop
    return queue


def unsubscribe(pid: str, queue: asyncio.Queue) -> None:
    with _LOCK:
        subscribers = _SUBSCRIBERS.get(pid, {})
        subscribers.pop(queue, None)
        if not subscribers:
            _SUBSCRIBERS.pop(pid, None)


def read_events(pid: str) -> list[dict]:
    with _LOCK:
        path = project_dir(pid) / "events.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def replay_and_subscribe(pid: str) -> tuple[list[dict], asyncio.Queue]:
    # 订阅与快照共用发布锁，避免回放交界处丢失或重复。
    with _LOCK:
        history = read_events(pid)
        return history, subscribe(pid)


class ToolResult:
    def __init__(self, summary: str) -> None:
        self.summary = "完成：" + summary
        self.status = "ok"

    def ok(self, summary: str) -> None:
        self.summary, self.status = summary, "ok"

    def warn(self, summary: str) -> None:
        self.summary, self.status = summary, "warn"


@contextmanager
def tool_call(pid: str, run: str, stage: str, tool: str, start_summary: str) -> Iterator[ToolResult]:
    args = dict(run=run, stage=stage, tool=tool)
    emit(pid, **args, status="start", summary=start_summary)
    result = ToolResult(start_summary)
    try:
        yield result
    except Exception as exc:
        emit(pid, **args, status="error", summary="工具执行失败，请检查输入资料或服务配置",
             detail={"error": str(exc), "type": type(exc).__name__})
        raise
    else:
        emit(pid, **args, status=result.status, summary=result.summary)
