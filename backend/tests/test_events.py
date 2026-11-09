import asyncio
import pytest
from app import events


def test_tool_success_warn_error(project):
    pid = project["id"]
    with events.tool_call(pid, "r1", "ingest", "pdf.extract", "开始抽取") as call:
        call.ok("抽取完成")
    with events.tool_call(pid, "r1", "ingest", "verify.facts", "开始核验") as call:
        call.warn("需要确认")
    with pytest.raises(RuntimeError):
        with events.tool_call(pid, "r1", "ingest", "pdf.extract", "开始抽取"):
            raise RuntimeError("损坏资料")
    result = events.read_events(pid)
    assert [item["status"] for item in result] == ["start", "ok", "start", "warn", "start", "error"]
    assert result[1]["summary"] == "抽取完成"
    assert "失败" in result[-1]["summary"]
    assert result[-1]["detail"]["error"] == "损坏资料"
    assert set(result[0]) == {"ts", "run", "stage", "tool", "status", "summary", "detail"}


@pytest.mark.asyncio
async def test_thread_broadcast_and_unsubscribe(project):
    pid = project["id"]
    first, second = events.subscribe(pid), events.subscribe(pid)
    event = await asyncio.to_thread(events.emit, pid, run="r1", stage="ingest", tool="pdf.extract", status="ok", summary="完成")
    assert await asyncio.wait_for(first.get(), 1) == event
    assert await asyncio.wait_for(second.get(), 1) == event
    events.unsubscribe(pid, first)
    events.unsubscribe(pid, second)
    assert pid not in events._SUBSCRIBERS
    assert events.read_events(pid) == [event]


@pytest.mark.asyncio
async def test_replay_snapshot_has_no_duplicate(project):
    pid = project["id"]
    events.emit(pid, run="r1", stage="ingest", tool="pdf.extract", status="start", summary="开始")
    history, queue = events.replay_and_subscribe(pid)
    events.emit(pid, run="r1", stage="ingest", tool="pdf.extract", status="ok", summary="完成")
    assert len(history) == 1 and history[0]["status"] == "start"
    assert (await asyncio.wait_for(queue.get(), 1))["status"] == "ok"
    assert queue.empty()
    events.unsubscribe(pid, queue)
