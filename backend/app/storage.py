"""项目存储与原子写入。"""
import json
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app import config

LOCK = RLock()


def safe_path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError("文件路径超出允许范围")
    return path


def project_dir(pid: str) -> Path:
    if not re.fullmatch(r"p[0-9a-f]{8}", pid):
        raise KeyError("项目编号无效")
    path = safe_path(config.PROJECTS_DIR, pid)
    if not path.is_dir():
        raise KeyError("项目不存在")
    return path


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp", dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            json.dump(data, out, ensure_ascii=False, indent=1, allow_nan=False)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def new_project(name: str, brief: str) -> dict:
    with LOCK:
        config.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        while True:
            pid = "p" + secrets.token_hex(4)
            path = config.PROJECTS_DIR / pid
            try:
                path.mkdir()
                break
            except FileExistsError:
                continue
        for folder in ("docs", "assets", "model", "tts", "renders", "llm"):
            (path / folder).mkdir()
        project = {"id": pid, "name": name, "brief": brief,
                   "created_at": datetime.now(timezone.utc).isoformat(), "model": None}
        write_json(pid, "project.json", project)
        return project


def read_json(pid: str, name: str, default: Any = None) -> Any:
    path = safe_path(project_dir(pid), name)
    with LOCK:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))


def write_json(pid: str, name: str, data: Any) -> None:
    with LOCK:
        atomic_json(safe_path(project_dir(pid), name), data)


def list_projects() -> list[dict]:
    with LOCK:
        result = [read_json(path.name, "project.json") for path in config.PROJECTS_DIR.glob("p????????")
                  if re.fullmatch(r"p[0-9a-f]{8}", path.name) and (path / "project.json").is_file()]
        return sorted(result, key=lambda item: item["created_at"], reverse=True)
