"""Tests for kb_ocr — hermetic, no OCR models required."""
from __future__ import annotations

from pathlib import Path

import pytest

import kb_common as kbc
import kb_ocr


def _cfg_with_media(tmp_path: Path, media_yaml: str) -> kbc.KbConfig:
    (tmp_path / "kb.config.yml").write_text(
        "knowledge_base:\n  name: t\n  mode: default\n" + media_yaml,
        encoding="utf-8",
    )
    return kbc.load_config(tmp_path)


def test_install_hint_mentions_rapidocr():
    hint = kb_ocr.install_hint()
    assert "rapidocr" in hint


def test_ocr_enabled_default_true():
    assert kb_ocr.ocr_enabled(None) is True


def test_ocr_disabled_via_config(tmp_path: Path):
    cfg = _cfg_with_media(tmp_path, "media:\n  ocr:\n    enabled: false\n")
    assert kb_ocr.ocr_enabled(cfg) is False


def test_available_backends_is_subset(tmp_path: Path):
    cfg = _cfg_with_media(tmp_path, "media:\n  ocr:\n    backends: [rapidocr]\n")
    usable = kb_ocr.available_backends(cfg)
    assert isinstance(usable, list)
    assert set(usable) <= {"rapidocr"}


def test_render_markdown_has_provenance():
    md = kb_ocr._render_markdown("scan.png", "some text", "rapidocr")
    assert "OCR: scan.png" in md
    assert "rapidocr" in md
    assert "some text" in md


def test_ocr_missing_file_raises():
    with pytest.raises(kb_ocr.OcrUnavailable):
        kb_ocr.ocr_image("/no/such/file.png")


def test_ocr_raises_when_no_backend(tmp_path: Path, monkeypatch):
    f = tmp_path / "fake.png"
    f.write_bytes(b"not really an image")
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: [])
    with pytest.raises(kb_ocr.OcrUnavailable):
        kb_ocr.ocr_image(f)
