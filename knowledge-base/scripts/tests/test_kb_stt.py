"""Tests for kb_stt (speech-to-text) — hermetic, no heavy models required."""
from __future__ import annotations

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
