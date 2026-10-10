"""Tests for session-summary saving."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest
import yaml

import kb_save_session


def _write_config(root: Path, *, redaction: bool = True) -> None:
    (root / "kb.config.yml").write_text(
        f"""
knowledge_base:
  name: test-kb
  mode: super
language_policy:
  primary: ru
privacy:
  require_redaction_for_chats: {str(redaction).lower()}
""".strip(),
        encoding="utf-8",
    )


def _meta(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])


def _sessions(root: Path) -> list[Path]:
    return sorted((root / "interactions" / "sessions").rglob("*.md"))


def _save(root: Path, title: str, summary: str, *extra: str) -> int:
    return kb_save_session.main(
        ["--root", str(root), "--title", title, "--summary", summary, *extra]
    )


def test_save_session_writes_summary_file(tmp_path: Path):
    _write_config(tmp_path)

    code = kb_save_session.main(
        [
            "--root", str(tmp_path),
            "--title", "Fix extraction issues",
            "--summary", "Reprocessed a stuck PDF asset and checked session logging.",
            "--decision", "Install missing Python packages first.",
            "--processed", "assets/documents/2026-07-01__manual.pdf",
            "--tag", "maintenance",
        ]
    )
    assert code == 0

    sessions = _sessions(tmp_path)
    assert len(sessions) == 1

    text = sessions[0].read_text(encoding="utf-8")
    meta = _meta(sessions[0])
    assert meta["title"] == "Fix extraction issues"
    assert meta["source"] == "manual"
    assert meta["meta_reviewed"] is False
    assert "## Summary" in text
    assert "## Decisions" in text
    assert "## Processed Materials" in text


def test_layout_is_a_dialogue_folder_with_timestamped_files(tmp_path: Path):
    # 07_INTERACTION_LOOP.md "Layout in interactions/sessions/":
    # <date>__<dialogue>/<date>T<HH-MM>__<slug>.md
    _write_config(tmp_path)
    assert _save(tmp_path, "Competitor analysis", "Found the mid-range gap.") == 0

    [path] = _sessions(tmp_path)
    rel = path.relative_to(tmp_path / "interactions" / "sessions").as_posix()
    today = dt.date.today().isoformat()
    assert re.fullmatch(
        rf"{today}__competitor-analysis/{today}T\d\d-\d\d__competitor-analysis\.md", rel
    ), rel


def test_same_title_twice_keeps_both_sessions(tmp_path: Path):
    # G:M8 / E-H6: the evening save replaced the morning one.
    _write_config(tmp_path)
    assert _save(tmp_path, "Daily sync", "Morning notes") == 0
    assert _save(tmp_path, "Daily sync", "Evening notes") == 0

    sessions = _sessions(tmp_path)
    assert len(sessions) == 2
    assert len({p.parent for p in sessions}) == 1  # one dialogue folder
    bodies = " ".join(p.read_text(encoding="utf-8") for p in sessions)
    assert "Morning notes" in bodies and "Evening notes" in bodies


def test_same_minute_gets_a_suffix_instead_of_overwriting(tmp_path: Path):
    _write_config(tmp_path)
    when = dt.datetime(2026, 5, 6, 10, 30, 12)
    kwargs = dict(
        root=tmp_path, title="Deep dive", decisions=[], processed=[],
        open_questions=[], tags=[], source="manual", now=when,
    )
    first = kb_save_session.save_session(summary="first", **kwargs)
    second = kb_save_session.save_session(summary="second", **kwargs)

    folder = tmp_path / "interactions" / "sessions" / "2026-05-06__deep-dive"
    assert first == folder / "2026-05-06T10-30__deep-dive.md"
    assert second == folder / "2026-05-06T10-30__deep-dive.v02.md"
    assert "first" in first.read_text(encoding="utf-8")
    assert "second" in second.read_text(encoding="utf-8")


def _skip_punctuation(path: Path) -> str:
    # Locale collations such as glibc ru_RU.UTF-8 (`find | sort`, `ls`)
    # compare names with the punctuation left out.
    return re.sub(r"[\W_]+", "", path.name.lower())


def test_sorted_listing_keeps_the_order_of_same_minute_saves(tmp_path: Path):
    # Review: `-2` sorted before the unsuffixed first save ('-' < '.'); a
    # `_02` suffix fixes byte order but not `sort` in a ru_RU locale.
    _write_config(tmp_path)
    kwargs = dict(
        root=tmp_path, title="Evening", decisions=[], processed=[],
        open_questions=[], tags=[], source="manual",
        now=dt.datetime(2026, 9, 24, 10, 20, 5),
    )
    saved = [kb_save_session.save_session(summary=f"save {i}", **kwargs) for i in range(1, 12)]
    assert _sessions(tmp_path) == saved
    assert sorted(saved, key=_skip_punctuation) == saved


def test_session_option_groups_saves_of_one_dialogue(tmp_path: Path):
    _write_config(tmp_path)
    existing = tmp_path / "interactions" / "sessions" / "2026-05-06__competitor-analysis"
    existing.mkdir(parents=True)

    assert _save(tmp_path, "Final summary", "Done.", "--session", existing.name) == 0
    assert _save(tmp_path, "Initial findings", "Start.", "--session", "Pricing review") == 0

    [reused] = list(existing.glob("*.md"))
    assert reused.name.endswith("__final-summary.md")
    today = dt.date.today().isoformat()
    new = tmp_path / "interactions" / "sessions" / f"{today}__pricing-review"
    assert [p.name.split("__", 1)[1] for p in new.glob("*.md")] == ["initial-findings.md"]


def test_session_option_cannot_escape_the_sessions_folder(tmp_path: Path):
    _write_config(tmp_path)
    assert _save(tmp_path, "x", "y", "--session", "../../outside") == 0
    [path] = _sessions(tmp_path)
    assert path.parent.parent == tmp_path / "interactions" / "sessions"
    assert not (tmp_path / "outside").exists()


def _plant_link(tmp_path: Path, name: str) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    sessions = tmp_path / "interactions" / "sessions"
    sessions.mkdir(parents=True)
    try:
        (sessions / name).symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    return outside


def test_a_planted_link_at_the_computed_folder_is_refused(tmp_path: Path, capsys):
    # Review: the <today>__<slug> fallback was never checked for a symlink.
    _write_config(tmp_path)
    today = dt.date.today().isoformat()
    outside = _plant_link(tmp_path, f"{today}__planted")

    assert _save(tmp_path, "T", "x", "--session", "planted") == 2
    assert "outside" in capsys.readouterr().err
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "log.md").exists()


def test_an_existing_folder_name_that_links_outside_is_refused(tmp_path: Path):
    _write_config(tmp_path)
    outside = _plant_link(tmp_path, "2026-05-06__linked")

    assert _save(tmp_path, "T", "x", "--session", "2026-05-06__linked") == 2
    assert list(outside.iterdir()) == []


def test_a_link_that_stays_inside_the_sessions_folder_is_followed(tmp_path: Path):
    _write_config(tmp_path)
    sessions = tmp_path / "interactions" / "sessions"
    real = sessions / "2026-05-06__real"
    real.mkdir(parents=True)
    try:
        (sessions / "2026-05-06__alias").symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")

    assert _save(tmp_path, "T", "x", "--session", "2026-05-06__alias") == 0
    assert [p.name.split("__", 1)[1] for p in real.glob("*.md")] == ["t.md"]


@pytest.mark.parametrize("required", [True, False])
def test_marks_redaction_required_never_redacted(tmp_path: Path, required: bool):
    # I15 / D10: the flag used to claim `redacted: true` without any redaction.
    _write_config(tmp_path, redaction=required)
    assert _save(tmp_path, "Chat recap", "Talked about the contract.") == 0
    meta = _meta(_sessions(tmp_path)[0])
    assert "redacted" not in meta
    assert meta["redaction_required"] is required


def test_logs_session_capture(tmp_path: Path):
    # 07_INTERACTION_LOOP.md: session-capture is recorded in log.md.
    _write_config(tmp_path)
    assert _save(tmp_path, "Auth refactor", "Split the middleware.") == 0
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    [path] = _sessions(tmp_path)
    assert "] session-capture | Auth refactor" in log
    assert f"- File: {path.relative_to(tmp_path).as_posix()}" in log


def test_refuses_a_folder_that_is_not_a_knowledge_base(tmp_path: Path, capsys):
    # G:M11: without kb.config.yml the summary landed in a phantom base.
    assert _save(tmp_path, "x", "y") == 2
    assert "kb.config.yml" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
