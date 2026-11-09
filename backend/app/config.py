"""运行目录配置。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
SAMPLES_DIR = ROOT / "samples"


def projects_dir() -> Path:
    return Path(os.environ.get("KEPU_PROJECTS_DIR", str(ROOT / "projects"))).resolve()


def __getattr__(name: str) -> Path:
    if name == "PROJECTS_DIR":
        return projects_dir()
    raise AttributeError(name)
