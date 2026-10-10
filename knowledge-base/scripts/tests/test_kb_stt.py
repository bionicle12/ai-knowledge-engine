"""Tests for kb_stt (speech-to-text) — hermetic, no heavy models required."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import kb_common as kbc
import kb_stt


def _cfg_with_media(tmp_path: Path, media_yaml: str) -> kbc.KbConfig:
    (tmp_path / "kb.config.yml").write_text(
        "knowledge_base:\n  name: t\n  mode: default\n" + media_yaml,
        encoding="utf-8",
    )
    return kbc.load_config(tmp_path)


def test_fmt_ts():
    assert kb_stt._fmt_ts(0) == "00:00"
    assert kb_stt._fmt_ts(65) == "01:05"
    assert kb_stt._fmt_ts(3661) == "1:01:01"
    assert kb_stt._fmt_ts(-5) == "00:00"


def test_render_markdown_with_timestamps():
    segs = [{"start": 0.0, "end": 2.0, "text": " hello "}, {"start": 2.0, "end": 4.0, "text": "world"}]
    md = kb_stt.render_markdown(
        source_name="a.mp3", language="en", segments=segs,
        timestamps=True, backend="faster-whisper", model="small", duration=4.0,
    )
    assert "[00:00]" in md and "hello" in md and "world" in md
    assert "faster-whisper" in md


def test_render_markdown_without_timestamps_is_paragraph():
    segs = [{"start": 0.0, "end": 2.0, "text": "hello"}, {"start": 2.0, "end": 4.0, "text": "world"}]
    md = kb_stt.render_markdown(
        source_name="a.mp3", language="en", segments=segs,
        timestamps=False, backend="x", model="small", duration=4.0,
    )
    assert "hello world" in md
    assert "[00:00]" not in md


def test_render_markdown_empty_segments():
    md = kb_stt.render_markdown(
        source_name="a.mp3", language="", segments=[],
        timestamps=True, backend="x", model="small", duration=0.0,
    )
    assert "empty transcript" in md


def test_install_hint_mentions_default_backend():
    hint = kb_stt.install_hint()
    assert "requirements-media.txt" in hint
    assert "faster-whisper" in hint


def test_stt_enabled_default_true_when_no_config():
    assert kb_stt.stt_enabled(None) is True


def test_stt_disabled_via_config(tmp_path: Path):
    cfg = _cfg_with_media(tmp_path, "media:\n  stt:\n    enabled: false\n")
    assert kb_stt.stt_enabled(cfg) is False


def test_available_backends_is_subset_of_configured(tmp_path: Path):
    cfg = _cfg_with_media(
        tmp_path, "media:\n  stt:\n    backends: [faster-whisper]\n"
    )
    usable = kb_stt.available_backends(cfg)
    assert isinstance(usable, list)
    assert set(usable) <= {"faster-whisper"}


def test_cloud_backend_never_listed_even_when_allow_cloud(tmp_path: Path):
    """Cloud STT is documented as future/opt-in but not implemented yet."""
    cfg = _cfg_with_media(
        tmp_path,
        "media:\n  stt:\n    allow_cloud: true\n    backends: [cloud, faster-whisper]\n",
    )
    usable = kb_stt.available_backends(cfg)
    assert "cloud" not in usable


def test_transcript_metadata_shape():
    result = kb_stt.TranscriptResult(
        text="hi", markdown="# x", language="en", backend="faster-whisper",
        model="small", duration=12.4, segments=[{"start": 0, "end": 1, "text": "hi"}],
    )
    meta = kb_stt.transcript_metadata(result)
    assert meta["stt_backend"] == "faster-whisper"
    assert meta["stt_model"] == "small"
    assert meta["stt_language"] == "en"
    assert meta["stt_segments"] == 1


def test_transcribe_missing_file_raises():
    with pytest.raises(kb_stt.SttUnavailable):
        kb_stt.transcribe("/no/such/file.mp3")


def test_transcribe_raises_when_no_backend(tmp_path: Path, monkeypatch):
    f = tmp_path / "fake.mp3"
    f.write_bytes(b"not really audio")
    monkeypatch.setattr(kb_stt, "available_backends", lambda cfg=None: [])
    with pytest.raises(kb_stt.SttUnavailable):
        kb_stt.transcribe(f)


# ---------------------------------------------------------------------------
# G:H6 — one model per process; L7 — honest message for a broken file
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_faster_whisper(monkeypatch):
    """A stand-in faster_whisper module that counts model constructions."""
    import types

    created: list[tuple] = []

    class Segment:
        start, end, text = 0.0, 1.0, "hello"

    class WhisperModel:
        fail_with: Exception | None = None
        init_fails_with: Exception | None = None

        def __init__(self, size, device, compute_type):
            if WhisperModel.init_fails_with is not None:
                raise WhisperModel.init_fails_with
            created.append((size, device, compute_type))

        def transcribe(self, path, language=None, vad_filter=True):
            if WhisperModel.fail_with is not None:
                raise WhisperModel.fail_with
            return iter([Segment()]), types.SimpleNamespace(language="en", duration=1.0)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WhisperModel))
    monkeypatch.setattr(kb_stt, "available_backends", lambda cfg=None: ["faster-whisper"])
    kb_stt._faster_whisper_model.cache_clear()
    yield WhisperModel, created
    kb_stt._faster_whisper_model.cache_clear()


def _media(tmp_path: Path, *names: str) -> list[Path]:
    files = []
    for name in names:
        f = tmp_path / name
        f.write_bytes(b"audio")
        files.append(f)
    return files


def test_whisper_model_loads_once_per_process(tmp_path: Path, fake_faster_whisper):
    _model, created = fake_faster_whisper
    for f in _media(tmp_path, "a.mp3", "b.mp3", "c.mp3"):
        assert kb_stt.transcribe(f).text == "hello"
    assert created == [("small", "auto", "int8")]


def test_openai_whisper_model_loads_once_per_process(tmp_path: Path, monkeypatch):
    import types

    loads: list[str] = []

    class Model:
        def transcribe(self, path, language=None):
            return {"text": "hi", "language": "en", "segments": []}

    def load_model(size):
        loads.append(size)
        return Model()

    monkeypatch.setitem(sys.modules, "whisper", types.SimpleNamespace(load_model=load_model))
    monkeypatch.setattr(kb_stt, "available_backends", lambda cfg=None: ["openai-whisper"])
    monkeypatch.setattr(kbc, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    kb_stt._openai_whisper_model.cache_clear()
    try:
        for f in _media(tmp_path, "a.wav", "b.wav"):
            kb_stt.transcribe(f)
    finally:
        kb_stt._openai_whisper_model.cache_clear()
    assert loads == ["small"]


def test_broken_file_reports_backend_error_not_missing_backend(tmp_path: Path, fake_faster_whisper):
    model, _created = fake_faster_whisper
    model.fail_with = ValueError("Invalid data found when processing input")
    (f,) = _media(tmp_path, "broken.mp3")
    with pytest.raises(kb_stt.SttUnavailable) as exc:
        kb_stt.transcribe(f)
    message = str(exc.value)
    assert "faster-whisper: ValueError: Invalid data found" in message
    assert "broken.mp3" in message and "damaged" in message
    assert "No speech-to-text backend available" not in message


def test_backend_that_cannot_import_keeps_the_install_hint(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import → ImportError
    monkeypatch.setattr(kb_stt, "available_backends", lambda cfg=None: ["faster-whisper"])
    kb_stt._faster_whisper_model.cache_clear()
    (f,) = _media(tmp_path, "a.mp3")
    with pytest.raises(kb_stt.SttUnavailable) as exc:
        kb_stt.transcribe(f)
    message = str(exc.value)
    assert "faster-whisper: ModuleNotFoundError" in message
    assert "requirements-media.txt" in message
    assert "failed on" not in message and "damaged" not in message


def test_model_that_cannot_load_is_a_setup_problem_not_a_damaged_file(tmp_path: Path, fake_faster_whisper):
    """Offline first run: the Hugging Face download fails inside WhisperModel()."""
    model, created = fake_faster_whisper
    model.init_fails_with = OSError(
        "LocalEntryNotFoundError: cannot find the requested files in the local cache"
    )
    (f,) = _media(tmp_path, "x.mp3")
    with pytest.raises(kb_stt.SttUnavailable) as exc:
        kb_stt.transcribe(f)
    message = str(exc.value)
    assert "faster-whisper: OSError: LocalEntryNotFoundError" in message
    assert "no STT backend could start" in message and "setup problem" in message
    assert "Hugging Face" in message
    assert "damaged" not in message and "likely cause" not in message
    model.init_fails_with = None  # the failed load is not cached: the next file retries
    assert kb_stt.transcribe(f).text == "hello"
    assert created == [("small", "auto", "int8")]


def test_one_backend_cannot_start_and_the_other_fails_on_the_file(tmp_path: Path, monkeypatch, fake_faster_whisper):
    import types

    model, _created = fake_faster_whisper
    model.init_fails_with = MemoryError("cannot allocate")

    class Model:
        def transcribe(self, path, language=None):
            raise RuntimeError("Invalid data found when processing input")

    monkeypatch.setitem(sys.modules, "whisper", types.SimpleNamespace(load_model=lambda size: Model()))
    monkeypatch.setattr(kb_stt, "available_backends", lambda cfg=None: ["faster-whisper", "openai-whisper"])
    monkeypatch.setattr(kbc, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    kb_stt._openai_whisper_model.cache_clear()
    (f,) = _media(tmp_path, "broken.mp3")
    try:
        with pytest.raises(kb_stt.SttUnavailable) as exc:
            kb_stt.transcribe(f)
    finally:
        kb_stt._openai_whisper_model.cache_clear()
    message = str(exc.value)
    assert "faster-whisper: MemoryError: cannot allocate" in message
    assert "openai-whisper: RuntimeError: Invalid data found" in message
    assert "failed on broken.mp3" in message and "likely cause" in message
