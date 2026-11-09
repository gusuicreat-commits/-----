import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.media import tts


def test_captions_words_and_sentence_boundaries():
    words = [{"start": 0, "end": 1, "text": "主梁"}, {"start": 1.5, "end": 3.5, "text": "很长"},
             {"start": 4, "end": 6, "text": "观察结构。"}]
    result = tts.make_captions("主梁很长，观察结构。", words, .35)
    assert result == [{"start": .35, "end": 3.85, "text": "主梁很长"},
                      {"start": 4.35, "end": 6.35, "text": "观察结构"}]
    sentence = tts.make_captions("这是主梁，这是支腿。", [{"start": 1, "end": 5, "text": "这是主梁，这是支腿。"}], 2)
    assert sentence == [{"start": 3, "end": 5, "text": "这是主梁"}, {"start": 5, "end": 7, "text": "这是支腿"}]


def test_captions_no_words_and_long_segments():
    result = tts.make_captions("梁长，支腿很高。", [], 1, duration_s=9)
    assert result == [{"start": 1, "end": 4, "text": "梁长"}, {"start": 4, "end": 10, "text": "支腿很高"}]
    result = tts.make_captions("啊" * 40 + "！", [], 0, duration_s=8)
    assert [len(c["text"]) for c in result] == [18, 18, 4]
    assert result[-1]["end"] == 8
    assert tts.make_captions("，。！？", [], 0) == []


def test_injected_engine_and_metadata(monkeypatch, tmp_path):
    def engine(text, out, **kwargs):
        assert kwargs == {"voice": "zh-CN-YunjianNeural", "rate": "+4%"}
        out.write_bytes(b"audio")
        return {"engine": "test", "words": []}
    monkeypatch.setattr(tts, "ENGINE", engine)
    monkeypatch.setattr(tts, "probe_duration", lambda path: 1.25)
    output = tmp_path / "S1.mp3"
    result = tts.synthesize("测试", output)
    assert result == {"engine": "test", "words": [], "duration_s": 1.25}
    assert json.loads(output.with_suffix(".words.json").read_text()) == result["words"]


@pytest.mark.parametrize("supports_word", [True, False])
def test_edge_offset_and_boundary_fallback(monkeypatch, tmp_path, supports_word):
    boundaries = []
    class Communicate:
        def __init__(self, text, voice, rate, boundary="SentenceBoundary"):
            boundaries.append(boundary)
            if boundary == "WordBoundary" and not supports_word:
                raise ValueError("不支持单词边界")
        async def stream(self):
            yield {"type": "audio", "data": b"audio"}
            yield {"type": "WordBoundary" if supports_word else "SentenceBoundary",
                   "offset": 5_000_000, "duration": 12_000_000, "text": "测试"}
    monkeypatch.setattr(tts.edge_tts, "Communicate", Communicate)
    monkeypatch.setattr(tts, "probe_duration", lambda path: 2)
    monkeypatch.delenv("KEPU_TTS_ENGINE", raising=False)
    result = tts.synthesize("测试", tmp_path / "S1.mp3")
    assert result["words"] == [{"start": .5, "end": 1.7, "text": "测试"}]
    assert boundaries == (["WordBoundary"] if supports_word else ["WordBoundary", "SentenceBoundary"])


def test_say_fallback_cleans_temporary_file(monkeypatch, tmp_path):
    async def fail(*args, **kwargs):
        raise OSError("网络不可用")
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == "say":
            Path(args[args.index("-o") + 1]).write_bytes(b"aiff")
        else:
            Path(args[-1]).write_bytes(b"mp3")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(tts, "_edge", fail)
    monkeypatch.setattr(tts.subprocess, "run", run)
    monkeypatch.setattr(tts, "probe_duration", lambda path: 2)
    monkeypatch.delenv("KEPU_TTS_ENGINE", raising=False)
    output = tmp_path / "S1.mp3"
    assert tts.synthesize("测试", output) == {"engine": "say", "words": [], "duration_s": 2}
    assert calls[0][:3] == ["say", "-v", "Tingting"]
    assert not output.with_suffix(".aiff").exists()


def test_fake_engine_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("KEPU_TTS_ENGINE", "fake")
    calls = []
    monkeypatch.setattr(tts.subprocess, "run", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(tts, "probe_duration", lambda path: .44)
    result = tts.synthesize("测试", tmp_path / "S1.mp3")
    assert result["engine"] == "fake" and result["words"][-1]["end"] == .44
    assert "anullsrc=r=48000:cl=mono" in calls[0]


def test_probe_env_and_invalid_duration(monkeypatch, tmp_path):
    monkeypatch.setenv("FFPROBE", "/custom/probe")
    def run(args, **kwargs):
        assert args[0] == "/custom/probe"
        return SimpleNamespace(stdout="nan")
    monkeypatch.setattr(tts.subprocess, "run", run)
    with pytest.raises(ValueError, match="时长无效"):
        tts.probe_duration(tmp_path / "audio.mp3")


def test_caption_preserves_decimal():
    result = tts.make_captions("焊缝误差0.5毫米。", [], 0, duration_s=3)
    assert len(result) == 1 and result[0]["text"] == "焊缝误差0.5毫米"
