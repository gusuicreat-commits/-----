import socket
import subprocess

import pytest
from app import config, llm, storage


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("KEPU_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("KEPU_LLM_MODE", "replay")
    monkeypatch.setenv("KEPU_LLM_CASSETTES", str(config.ROOT / "backend/tests/cassettes"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("测试禁止联网或调用真实大模型")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(llm.anthropic, "Anthropic", forbidden)


@pytest.fixture
def project():
    return storage.new_project("测试项目", "解释门机")


@pytest.fixture
def sample_pdf():
    return config.SAMPLES_DIR / "示例技术参数表.pdf"
