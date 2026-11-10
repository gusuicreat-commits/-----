from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import main, storage


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(main.app) as client:
        yield client


@pytest.mark.parametrize("missing_directory", [False, True])
def test_empty_logs(client: TestClient, project: dict, missing_directory: bool) -> None:
    pid = project["id"]
    directory = storage.project_dir(pid) / "llm"
    if missing_directory:
        directory.rmdir()
    response = client.get(f"/api/projects/{pid}/llm")
    assert response.status_code == 200
    assert response.json() == {"calls": []}
    assert directory.exists() is not missing_directory


def test_logs_sorted_and_summary_only(client: TestClient, project: dict) -> None:
    pid = project["id"]
    directory = storage.project_dir(pid) / "llm"
    records = {
        "010_custom_task.json": {"task": "custom_task", "backend": "sdk", "cost_usd": 0},
        "003_plan.json": {"task": "plan", "backend": "replay"},
        "001_extract_facts.json": {
            "task": "extract_facts", "backend": "cli", "cost_usd": 0.027,
            "started_at": "2026-11-10T01:02:03+00:00", "duration_s": 1.25,
            "system_head": "内部提示", "user_head": "资料内容", "response": {"facts": []},
            "images": ["内部路径"], "error": "内部错误", "model": "内部模型标识",
        },
        "011_missing_fields.json": {},
    }
    for name, record in records.items():
        storage.write_json(pid, f"llm/{name}", record)
    (directory / "unfinished.tmp").write_text("未完成", encoding="utf-8")
    (directory / "nested.json").mkdir()
    storage.atomic_json(directory / "nested.json" / "ignored.json", {"backend": "cli"})
    before = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}

    response = client.get(f"/api/projects/{pid}/llm")

    assert response.status_code == 200
    assert response.json() == {"calls": [
        {"file": "001_extract_facts.json", "task": "extract_facts", "backend": "cli",
         "cost_usd": 0.027, "started_at": "2026-11-10T01:02:03+00:00", "duration_s": 1.25},
        {"file": "003_plan.json", "task": "plan", "backend": "replay",
         "cost_usd": None, "started_at": None, "duration_s": None},
        {"file": "010_custom_task.json", "task": "custom_task", "backend": "sdk",
         "cost_usd": 0, "started_at": None, "duration_s": None},
        {"file": "011_missing_fields.json", "task": None, "backend": None,
         "cost_usd": None, "started_at": None, "duration_s": None},
    ]}
    assert {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()} == before


@pytest.mark.parametrize("pid", ["invalid", "p00000000"])
def test_unknown_project(client: TestClient, pid: str) -> None:
    assert client.get(f"/api/projects/{pid}/llm").status_code == 404
