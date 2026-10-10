"""The requirements templates keep the base install light (E-H9)."""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def _packages(name: str) -> set[str]:
    """Package names a requirements file installs (comments and -r lines skipped)."""
    packages = set()
    for line in (TEMPLATES / name).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            packages.add(re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower())
    return packages


def test_keybert_and_torch_stay_out_of_the_base_install():
    base = _packages("requirements.txt")
    assert "keybert" not in base and "torch" not in base
    assert {"spacy", "rake-nltk"} <= base  # NER + RAKE keywords still come with the base


def test_keybert_lives_in_requirements_nlp_with_a_cpu_torch_note():
    assert _packages("requirements-nlp.txt") == {"keybert"}
    text = (TEMPLATES / "requirements-nlp.txt").read_text(encoding="utf-8")
    assert "--index-url https://download.pytorch.org/whl/cpu" in text


def test_base_requirements_tell_how_to_get_the_nltk_data_rake_needs():
    text = (TEMPLATES / "requirements.txt").read_text(encoding="utf-8")
    assert "python3 -m nltk.downloader stopwords punkt" in text


def test_ocr_comments_do_not_promise_every_language_out_of_the_box():
    """rapidocr reads Chinese/English only; the comments must say how to get the rest."""
    base = (TEMPLATES / "requirements.txt").read_text(encoding="utf-8")
    assert "both work out of the box" not in base
    assert "Chinese" in base and "English" in base
    media = (TEMPLATES / "requirements-media.txt").read_text(encoding="utf-8")
    assert "tesseract-ocr-rus" in media and "brew install tesseract tesseract-lang" in media
    assert "Additional language data" in media and "kb_ocr.py --check" in media
