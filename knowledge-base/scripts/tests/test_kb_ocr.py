"""Tests for kb_ocr — hermetic, no OCR models required."""
from __future__ import annotations

import sys
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


# ---------------------------------------------------------------------------
# G:H6 — one engine per process; L6 — ocr.language; L7 — broken file message
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_rapidocr(monkeypatch):
    """A stand-in rapidocr_onnxruntime module that counts engine constructions."""
    import types

    created: list[int] = []

    class RapidOCR:
        fail_with: Exception | None = None
        init_fails_with: Exception | None = None

        def __init__(self):
            if RapidOCR.init_fails_with is not None:
                raise RapidOCR.init_fails_with
            created.append(1)

        def __call__(self, path):
            if RapidOCR.fail_with is not None:
                raise RapidOCR.fail_with
            return [([0, 0], "Invoice 42", 0.9)], 0.01

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=RapidOCR))
    kb_ocr._rapidocr_engine.cache_clear()
    yield RapidOCR, created
    kb_ocr._rapidocr_engine.cache_clear()


class TesseractError(RuntimeError):
    """What pytesseract raises when the tesseract run fails."""


def _install_fake_tesseract(monkeypatch, installed: list[str] | None) -> list[str]:
    """Stand-in pytesseract + PIL recording the ``lang`` Tesseract is given.

    ``installed`` = the language data ``tesseract --list-langs`` reports (a
    requested language outside it fails like real Tesseract); ``None`` = an old
    pytesseract without ``get_languages``.
    """
    import types

    calls: list[str] = []

    class Image:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def image_to_string(image, lang=None):
        calls.append(lang)
        known = set(installed or ["eng", "rus"])
        for name in (lang or "eng").split("+"):
            if name not in known:
                raise TesseractError(1, f"Failed loading language '{name}' Tesseract couldn't load any languages!")
        return "Счёт 42\n"

    module = types.SimpleNamespace(image_to_string=image_to_string)
    if installed is not None:
        module.get_languages = lambda config="": [*installed, "osd"]
    monkeypatch.setitem(sys.modules, "pytesseract", module)
    monkeypatch.setitem(sys.modules, "PIL", types.SimpleNamespace(Image=types.SimpleNamespace(open=lambda p: Image())))
    return calls


@pytest.fixture
def fake_tesseract(monkeypatch):
    return _install_fake_tesseract(monkeypatch, None)


def _image(tmp_path: Path, name: str = "scan.png") -> Path:
    f = tmp_path / name
    f.write_bytes(b"png")
    return f


def test_rapidocr_engine_loads_once_per_process(tmp_path: Path, monkeypatch, fake_rapidocr):
    _engine, created = fake_rapidocr
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["rapidocr"])
    for name in ("a.png", "b.png", "c.png"):
        assert kb_ocr.ocr_image(_image(tmp_path, name)).text == "Invoice 42"
    assert created == [1]


def test_ocr_language_reaches_tesseract_as_tesseract_codes(tmp_path: Path, fake_tesseract):
    cfg = _cfg_with_media(tmp_path, "media:\n  ocr:\n    backends: [tesseract]\n    language: ru+en\n")
    result = kb_ocr._ocr_tesseract(_image(tmp_path), kb_ocr.ocr_languages(cfg))
    assert fake_tesseract == ["rus+eng"]
    assert result.backend == "tesseract"


def test_auto_language_is_the_primary_language_plus_english(tmp_path: Path):
    cfg = _cfg_with_media(tmp_path, "language_policy:\n  primary: ru\n")
    assert kb_ocr.ocr_languages(cfg) == ["ru", "en"]
    assert kb_ocr.ocr_languages(None) == ["en"]
    assert kb_ocr.ocr_languages(cfg, "de") == ["de"]


def test_cyrillic_prefers_tesseract_over_rapidocr(tmp_path: Path, monkeypatch, fake_rapidocr, fake_tesseract):
    cfg = _cfg_with_media(tmp_path, "media:\n  ocr:\n    language: ru\n")
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["rapidocr", "tesseract"])
    result = kb_ocr.ocr_image(_image(tmp_path), cfg=cfg)
    assert result.backend == "tesseract"
    assert fake_tesseract == ["rus"]


def test_rapidocr_alone_warns_that_cyrillic_may_be_garbled(tmp_path: Path, monkeypatch, fake_rapidocr):
    cfg = _cfg_with_media(tmp_path, "media:\n  ocr:\n    language: ru\n")
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["rapidocr"])
    result = kb_ocr.ocr_image(_image(tmp_path), cfg=cfg)
    assert result.backend == "rapidocr"
    assert "ru may be garbled" in result.warning
    assert "⚠️" in result.markdown and "Tesseract" in result.markdown
    english = _cfg_with_media(tmp_path, "media:\n  ocr:\n    language: en\n")
    assert kb_ocr.ocr_image(_image(tmp_path), cfg=english).warning == ""


def test_broken_image_reports_backend_error_not_missing_backend(tmp_path: Path, monkeypatch, fake_rapidocr):
    engine, _created = fake_rapidocr
    engine.fail_with = ValueError("cannot identify image file")
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["rapidocr"])
    with pytest.raises(kb_ocr.OcrUnavailable) as exc:
        kb_ocr.ocr_image(_image(tmp_path, "broken.png"))
    message = str(exc.value)
    assert "rapidocr: ValueError: cannot identify image file" in message
    assert "broken.png" in message and "damaged" in message
    assert "No OCR backend available" not in message


# ---------------------------------------------------------------------------
# Review round 2: Tesseract language data, start-up failures, language values
# ---------------------------------------------------------------------------


def test_tesseract_without_the_language_data_reads_with_what_it_has(tmp_path: Path, monkeypatch):
    """A default Tesseract install has English only; `auto` on a Russian base
    used to request rus+eng and fail on every image."""
    calls = _install_fake_tesseract(monkeypatch, ["eng"])
    cfg = _cfg_with_media(
        tmp_path, "language_policy:\n  primary: ru\nmedia:\n  ocr:\n    backends: [tesseract]\n"
    )
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["tesseract"])
    result = kb_ocr.ocr_image(_image(tmp_path), cfg=cfg)
    assert calls == ["eng"]
    assert result.backend == "tesseract" and result.text
    assert "no language data for rus" in result.warning
    assert "⚠️" in result.markdown


def test_tesseract_with_none_of_the_languages_uses_its_default(tmp_path: Path, monkeypatch):
    calls = _install_fake_tesseract(monkeypatch, ["eng"])
    result = kb_ocr._ocr_tesseract(_image(tmp_path), ["ru"], kb_ocr.tesseract_installed_languages())
    assert calls == [None] and "rus" in result.warning


def test_rapidocr_stays_first_when_tesseract_lacks_the_language(tmp_path: Path, monkeypatch, fake_rapidocr):
    calls = _install_fake_tesseract(monkeypatch, ["eng"])
    cfg = _cfg_with_media(tmp_path, "media:\n  ocr:\n    language: ru\n")
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["rapidocr", "tesseract"])
    result = kb_ocr.ocr_image(_image(tmp_path), cfg=cfg)
    assert result.backend == "rapidocr" and "may be garbled" in result.warning
    assert calls == []


def test_tesseract_missing_language_data_is_a_setup_problem_not_the_file(tmp_path: Path, monkeypatch):
    """When the data cannot be listed (old pytesseract), the failure must not
    blame the file."""
    calls = _install_fake_tesseract(monkeypatch, None)  # has eng + rus, cannot list them
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["tesseract"])
    with pytest.raises(kb_ocr.OcrUnavailable) as exc:
        kb_ocr.ocr_image(_image(tmp_path), language="kk")
    message = str(exc.value)
    assert "no OCR backend could start" in message and "setup problem" in message
    assert calls == ["kaz"] and "Failed loading language 'kaz'" in message
    assert "damaged" not in message and "likely cause" not in message


def test_rapidocr_engine_that_cannot_start_is_not_blamed_on_the_file(tmp_path: Path, monkeypatch, fake_rapidocr):
    engine, _created = fake_rapidocr
    engine.init_fails_with = RuntimeError("onnxruntime: failed to create session")
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["rapidocr"])
    with pytest.raises(kb_ocr.OcrUnavailable) as exc:
        kb_ocr.ocr_image(_image(tmp_path))
    message = str(exc.value)
    assert "rapidocr: RuntimeError: onnxruntime: failed to create session" in message
    assert "no OCR backend could start" in message and "setup problem" in message
    assert "damaged" not in message
    engine.init_fails_with = None  # the failed load is not cached: the next image retries
    assert kb_ocr.ocr_image(_image(tmp_path, "next.png")).text == "Invoice 42"


def test_backend_that_cannot_import_gets_the_install_hint_without_blaming_the_file(tmp_path: Path, monkeypatch):
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)  # import → ImportError
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["rapidocr"])
    kb_ocr._rapidocr_engine.cache_clear()
    with pytest.raises(kb_ocr.OcrUnavailable) as exc:
        kb_ocr.ocr_image(_image(tmp_path))
    message = str(exc.value)
    assert "rapidocr: ModuleNotFoundError" in message and "pip install rapidocr-onnxruntime" in message
    assert "failed on" not in message and "damaged" not in message


def test_ocr_language_accepts_a_yaml_list_and_region_tags(tmp_path: Path):
    listed = _cfg_with_media(tmp_path, "media:\n  ocr:\n    language: [ru, EN]\n")
    assert kb_ocr.ocr_languages(listed) == ["ru", "en"]
    assert kb_ocr._tesseract_plan(kb_ocr.ocr_languages(listed), None) == ("rus+eng", [])
    region = _cfg_with_media(tmp_path, "language_policy:\n  primary: ru-RU\n")
    assert kb_ocr.ocr_languages(region) == ["ru", "en"]
    assert kb_ocr.ocr_languages(None, "ru_RU+chi_sim") == ["ru", "chi_sim"]
    assert kb_ocr._tesseract_plan(["ru", "chi_sim"], {"eng", "rus"}) == ("rus", ["chi_sim"])


def test_check_lists_missing_tesseract_language_data(tmp_path: Path, monkeypatch, capsys):
    _install_fake_tesseract(monkeypatch, ["eng"])
    _cfg_with_media(tmp_path, "language_policy:\n  primary: ru\n")
    monkeypatch.setattr(kb_ocr, "available_backends", lambda cfg=None: ["tesseract"])
    assert kb_ocr.main(["--root", str(tmp_path), "--check"]) == 0
    out = capsys.readouterr().out
    assert "OCR languages: ru+en" in out
    assert "Tesseract language data: eng, osd — missing rus" in out
    assert "Tesseract is tried first" not in out
