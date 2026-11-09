import json
import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from app import config, storage


def test_create_list_and_dynamic_directory(monkeypatch, tmp_path):
    first = storage.new_project("中文项目", "说明")
    second = storage.new_project("第二个", "说明")
    assert re.fullmatch(r"p[0-9a-f]{8}", first["id"])
    directory = storage.project_dir(first["id"])
    assert {p.name for p in directory.iterdir()} == {"project.json", "docs", "assets", "model", "tts", "renders", "llm"}
    assert first["model"] is None
    assert storage.list_projects() == [second, first]
    monkeypatch.setenv("KEPU_PROJECTS_DIR", str(tmp_path / "other"))
    assert config.PROJECTS_DIR == tmp_path / "other"
    assert storage.list_projects() == []


@pytest.mark.parametrize("pid", ["../secret", "p1234567A", "p123", "p00000000"])
def test_invalid_project(pid):
    with pytest.raises(KeyError):
        storage.project_dir(pid)


def test_atomic_json_and_path_safety(project, tmp_path):
    pid = project["id"]
    assert storage.read_json(pid, "facts.json", {}) == {}
    storage.write_json(pid, "facts.json", {"说明": "中文"})
    path = storage.project_dir(pid) / "facts.json"
    assert ' "说明": "中文"' in path.read_text()
    assert not list(path.parent.glob("*.tmp"))
    with pytest.raises(ValueError):
        storage.write_json(pid, "../outside.json", {})
    (path.parent / "link").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        storage.read_json(pid, "link/outside.json", {})
    with pytest.raises(ValueError):
        storage.write_json(pid, "facts.json", {"invalid": float("nan")})
    assert storage.read_json(pid, "facts.json") == {"说明": "中文"}
    assert not list(path.parent.glob("*.tmp"))


def test_concurrent_writes(project):
    pid = project["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: storage.write_json(pid, "data.json", {"n": n}), range(20)))
    assert isinstance(json.loads((storage.project_dir(pid) / "data.json").read_text())["n"], int)
