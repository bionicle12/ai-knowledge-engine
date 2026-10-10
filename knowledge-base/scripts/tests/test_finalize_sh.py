"""Integration tests for shell/finalize.sh.

Tests the post-deploy flattening behavior: knowledge-base/ contents promoted
to project root, then both setup/ and knowledge-base/ removed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FINALIZE_SH = REPO_ROOT / "knowledge-base" / "shell" / "finalize.sh"


def _bash_can_see_repo() -> bool:
    """True when a usable bash is on PATH and it understands Windows paths.

    On Windows, PATH may resolve `bash` to WSL, which cannot see C:/ paths
    directly — these integration tests would fail for environment reasons.
    """
    try:
        result = subprocess.run(
            ["bash", "-c", f"test -f '{FINALIZE_SH.as_posix()}'"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _bash_can_see_repo(),
    reason="requires a bash that can access the repository path (e.g. Git Bash)",
)


def _stage_kit(root: Path) -> Path:
    """setup/ = the engine kit: the modules plus shell/finalize.sh."""
    setup = root / "setup" / "shell"
    setup.mkdir(parents=True)
    (root / "setup" / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "setup" / "00_OVERVIEW.md").write_text("# 00 (setup)\n", encoding="utf-8")
    return setup


def _stage_project(root: Path, *, valid: bool = True) -> Path:
    """Create a fake deployed project layout."""
    setup = _stage_kit(root)
    # Symlink real finalize.sh — script runs as if it were inside the project.
    # Windows needs Developer Mode / admin rights for symlinks; a copy behaves
    # identically for the script, so fall back to that.
    try:
        (setup / "finalize.sh").symlink_to(FINALIZE_SH)
    except OSError:
        shutil.copy2(FINALIZE_SH, setup / "finalize.sh")

    kb = root / "knowledge-base"
    kb.mkdir()

    if valid:
        # Required files for finalize to accept the base
        (kb / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
        (kb / "kb.config.yml").write_text(
            "knowledge_base:\n  name: test\n", encoding="utf-8"
        )
        (kb / "scripts").mkdir()
        (kb / "scripts" / "kb_ingest.py").write_text("# stub\n", encoding="utf-8")

    # Some additional realistic content
    (kb / "raw").mkdir(exist_ok=True)
    (kb / "knowledge").mkdir(exist_ok=True)
    (kb / "reindex.sh").write_text("echo hi\n", encoding="utf-8")
    return kb


def _run_finalize(
    root: Path, *args: str, stdin: str = ""
) -> subprocess.CompletedProcess:
    """Run setup/shell/finalize.sh from the project root, as 02_INIT says."""
    return subprocess.run(
        ["bash", str(root / "setup" / "shell" / "finalize.sh"), *args],
        capture_output=True,
        text=True,
        check=False,
        input=stdin,
        cwd=root,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_finalize_promotes_kb_to_root(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path)
    assert result.returncode == 0, result.stderr
    # Content should be promoted
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "kb.config.yml").is_file()
    assert (tmp_path / "scripts" / "kb_ingest.py").is_file()
    assert (tmp_path / "knowledge").is_dir()
    assert (tmp_path / "raw").is_dir()
    # Containers should be gone
    assert not (tmp_path / "knowledge-base").exists()
    assert not (tmp_path / "setup").exists()


def test_finalize_keep_setup_flag(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path, "--keep-setup")
    assert result.returncode == 0
    assert not (tmp_path / "knowledge-base").exists()
    assert (tmp_path / "setup").is_dir(), "--keep-setup should retain setup/"


def test_finalize_dry_run_changes_nothing(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path, "--dry-run")
    assert result.returncode == 0
    # Nothing should have moved
    assert (tmp_path / "knowledge-base" / "AGENTS.md").is_file()
    assert (tmp_path / "setup").is_dir()
    assert not (tmp_path / "AGENTS.md").exists()


# ---------------------------------------------------------------------------
# Refusal paths
# ---------------------------------------------------------------------------


def test_finalize_refuses_when_kb_missing(tmp_path: Path):
    setup = _stage_kit(tmp_path)
    try:
        (setup / "finalize.sh").symlink_to(FINALIZE_SH)
    except OSError:
        shutil.copy2(FINALIZE_SH, setup / "finalize.sh")
    # No knowledge-base/ created
    result = _run_finalize(tmp_path)
    assert result.returncode == 1
    assert "deployed base not found" in result.stderr.lower()


def test_finalize_refuses_when_required_files_missing(tmp_path: Path):
    _stage_project(tmp_path, valid=False)
    result = _run_finalize(tmp_path)
    assert result.returncode == 1
    assert "missing required files" in result.stderr.lower()
    # Still nothing moved
    assert not (tmp_path / "AGENTS.md").exists()


def test_finalize_refuses_on_conflicts(tmp_path: Path):
    _stage_project(tmp_path)
    # Pre-existing AGENTS.md at project root → conflict
    (tmp_path / "AGENTS.md").write_text("preexisting\n", encoding="utf-8")
    result = _run_finalize(tmp_path)
    assert result.returncode == 1
    assert "would be overwritten" in result.stderr.lower()
    # Original preserved
    assert (tmp_path / "AGENTS.md").read_text() == "preexisting\n"


def test_finalize_force_overwrites_conflicts(tmp_path: Path):
    _stage_project(tmp_path)
    (tmp_path / "AGENTS.md").write_text("preexisting\n", encoding="utf-8")
    result = _run_finalize(tmp_path, "--force")
    assert result.returncode == 0
    assert "AGENTS" in (tmp_path / "AGENTS.md").read_text()
    # The deployed AGENTS.md replaced the pre-existing one
    assert (tmp_path / "AGENTS.md").read_text() != "preexisting\n"


# ---------------------------------------------------------------------------
# Idempotency / re-runs
# ---------------------------------------------------------------------------


def test_finalize_second_run_is_safe(tmp_path: Path):
    _stage_project(tmp_path)
    first = _run_finalize(tmp_path)
    assert first.returncode == 0
    # No setup/ left, so a second invocation requires a fresh path
    # Just verify the project state is intact
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "scripts" / "kb_ingest.py").is_file()


# ---------------------------------------------------------------------------
# Launcher promotion + duplicate cleanup (0.9.3)
# ---------------------------------------------------------------------------


def _stage_project_with_launchers(root: Path) -> Path:
    """Stage a project where knowledge-base/ has both shell/*.command and
    duplicated *.sh at its own root — like what the agent currently does."""
    kb = _stage_project(root)
    sh = kb / "shell"
    sh.mkdir(exist_ok=True)
    # Real shell scripts live in shell/
    (sh / "watcher.sh").write_text("echo watcher\n", encoding="utf-8")
    (sh / "lint.sh").write_text("echo lint\n", encoding="utf-8")
    # macOS launchers (also in shell/ before finalize)
    (sh / "watcher-start.command").write_text("#!/bin/bash\necho start\n",
                                              encoding="utf-8")
    (sh / "watcher-stop.command").write_text("#!/bin/bash\necho stop\n",
                                             encoding="utf-8")
    (sh / "reindex.command").write_text("#!/bin/bash\necho reindex\n",
                                        encoding="utf-8")
    # Windows launchers
    (sh / "watcher-start.bat").write_text("@echo start\r\n", encoding="utf-8")
    # The agent currently also drops a *.sh duplicate at the kb root.
    # finalize.sh should detect and remove these duplicates.
    (kb / "watcher.sh").write_text("echo watcher\n", encoding="utf-8")
    (kb / "lint.sh").write_text("echo lint\n", encoding="utf-8")
    return kb


def test_finalize_promotes_command_launchers_to_root(tmp_path: Path):
    _stage_project_with_launchers(tmp_path)
    result = _run_finalize(tmp_path)
    assert result.returncode == 0, result.stderr
    # macOS launchers should now be at project root
    assert (tmp_path / "watcher-start.command").is_file()
    assert (tmp_path / "watcher-stop.command").is_file()
    assert (tmp_path / "reindex.command").is_file()
    # Windows launcher too
    assert (tmp_path / "watcher-start.bat").is_file()
    # And NOT in shell/ anymore
    assert not (tmp_path / "shell" / "watcher-start.command").exists()
    assert not (tmp_path / "shell" / "reindex.command").exists()
    assert not (tmp_path / "shell" / "watcher-start.bat").exists()


def test_finalize_keeps_sh_in_shell_only(tmp_path: Path):
    _stage_project_with_launchers(tmp_path)
    result = _run_finalize(tmp_path)
    assert result.returncode == 0
    # *.sh should live in shell/ — duplicates at root removed
    assert (tmp_path / "shell" / "watcher.sh").is_file()
    assert (tmp_path / "shell" / "lint.sh").is_file()
    assert not (tmp_path / "watcher.sh").exists(), \
        "watcher.sh duplicate at root should be cleaned up"
    assert not (tmp_path / "lint.sh").exists()


def test_finalize_preserves_root_sh_when_different(tmp_path: Path):
    """If a *.sh at the root differs from the shell/ copy, keep both —
    user may have customized. Only identical copies are pruned."""
    _stage_project_with_launchers(tmp_path)
    # Make the root copy different
    kb = tmp_path / "knowledge-base"
    (kb / "watcher.sh").write_text("echo CUSTOM\n", encoding="utf-8")
    result = _run_finalize(tmp_path)
    assert result.returncode == 0
    # Custom version preserved at root
    assert (tmp_path / "watcher.sh").read_text() == "echo CUSTOM\n"
    # shell/ copy still there too
    assert (tmp_path / "shell" / "watcher.sh").is_file()


def test_finalize_promotion_does_not_overwrite_existing_root_launcher(tmp_path: Path):
    _stage_project_with_launchers(tmp_path)
    kb = tmp_path / "knowledge-base"
    # Pre-existing root launcher with custom content (someone customized)
    (kb / "watcher-start.command").write_text(
        "#!/bin/bash\necho USER_CUSTOM\n", encoding="utf-8"
    )
    result = _run_finalize(tmp_path)
    assert result.returncode == 0
    # Root version preserved as-is
    assert (tmp_path / "watcher-start.command").read_text() == \
        "#!/bin/bash\necho USER_CUSTOM\n"
    # shell/ duplicate also kept since promotion was skipped
    assert (tmp_path / "shell" / "watcher-start.command").is_file()


def test_finalize_writes_one_line_claude_md_on_yes(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path, stdin="y\n")
    assert result.returncode == 0, result.stderr + result.stdout
    claude = tmp_path / "CLAUDE.md"
    assert claude.is_file()
    assert claude.read_text(encoding="utf-8") == "@AGENTS.md\n"


def test_finalize_skips_claude_md_on_empty_or_no(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path, stdin="n\n")
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (tmp_path / "CLAUDE.md").exists()


def test_finalize_claude_md_flag_writes_without_prompt(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path, "--claude-md")
    assert result.returncode == 0, result.stderr + result.stdout
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"


def test_finalize_dry_run_does_not_write_claude_md(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path, "--dry-run", "--claude-md")
    assert result.returncode == 0
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / "knowledge-base" / "CLAUDE.md").exists()


# ---------------------------------------------------------------------------
# 0.16.0: .git / venv safety, backups, kb-docs/, journal + --resume, CLAUDE.md
# ---------------------------------------------------------------------------


def _venv(path: Path, marker: str) -> None:
    path.mkdir(parents=True)
    (path / "pyvenv.cfg").write_text(f"home = /usr/bin\n# {marker}\n", encoding="utf-8")
    (path / "marker").write_text(marker, encoding="utf-8")


def _setup_modules(root: Path) -> None:
    for name in ("00_OVERVIEW.md", "16_MERGE.md", "18_HEAL.md", "README.md"):
        (root / "setup" / name).write_text(f"# {name} (setup)\n", encoding="utf-8")


def test_finalize_force_never_moves_or_deletes_git_and_venv(tmp_path: Path):
    """Q1: --force used to rm -rf the project's .git and .venv."""
    kb = _stage_project(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    _venv(tmp_path / ".venv", "project venv")
    (kb / ".git").mkdir()
    (kb / ".git" / "HEAD").write_text("base repo\n", encoding="utf-8")
    _venv(kb / ".venv", "base venv")
    (tmp_path / "README.md").write_text("project readme\n", encoding="utf-8")
    (kb / "README.md").write_text("base readme\n", encoding="utf-8")

    result = _run_finalize(tmp_path, "--force", "--no-claude-md")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / ".git" / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/main\n"
    assert (tmp_path / ".venv" / "marker").read_text(encoding="utf-8") == "project venv"
    assert not (tmp_path / ".venv" / ".venv").exists()
    # The base's own repository and venv are left where they are, with a warning.
    assert (kb / ".git" / "HEAD").is_file()
    assert (kb / ".venv" / "marker").is_file()
    assert "stays in place" in result.stdout
    # E-H8 follow-up: the venv hint names the venv folder only — deleting all of
    # knowledge-base/ would take the .git the previous warning kept on purpose.
    assert "delete knowledge-base/.venv yourself" in result.stdout
    assert "delete knowledge-base/ yourself" not in result.stdout
    # The conflicting README was moved aside, not deleted.
    backups = list((tmp_path / ".kb-finalize-backup").glob("*/README.md"))
    assert [p.read_text(encoding="utf-8") for p in backups] == ["project readme\n"]
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "base readme\n"


def test_finalize_refuses_to_run_from_the_bases_own_copy(tmp_path: Path):
    """The base's shell/finalize.sh treats knowledge-base/ as setup/ and would
    delete it at the end — together with the .git/.venv kept in place there."""
    kb = _stage_project(tmp_path)
    (kb / "shell").mkdir()
    shutil.copy2(FINALIZE_SH, kb / "shell" / "finalize.sh")
    (kb / ".git").mkdir()
    (kb / ".git" / "HEAD").write_text("base repo\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(kb / "shell" / "finalize.sh"), "--no-claude-md"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "setup/shell/finalize.sh" in result.stderr
    assert (kb / ".git" / "HEAD").is_file()
    assert (kb / "AGENTS.md").is_file()
    assert not (tmp_path / "AGENTS.md").exists()


def _finalized_base(path: Path) -> Path:
    """A base after finalize: it ships shell/finalize.sh like every base."""
    (path / "shell").mkdir(parents=True)
    shutil.copy2(FINALIZE_SH, path / "shell" / "finalize.sh")
    for name, text in (("AGENTS.md", "# AGENTS\n"), ("kb.config.yml", "knowledge_base:\n  name: t\n"),
                       (".git/HEAD", "base repo\n"), (".venv/pyvenv.cfg", "home = /usr/bin\n"),
                       ("knowledge/page.md", "# page\n"), ("scripts/kb_ingest.py", "# stub\n")):
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("setup_kind", ["finalized-base", "not-a-kit"])
def test_finalize_runs_only_from_the_kit(tmp_path: Path, setup_kind: str):
    """Q1 follow-up / D8: a finalized base's own shell/finalize.sh took the base
    for setup/, moved a neighbouring knowledge-base/ into the parent folder and
    then deleted the whole base (.git, .venv, knowledge/) as "setup/"."""
    parent = tmp_path / "parent"
    neighbour = _stage_project(parent)  # parent/setup + parent/knowledge-base
    (parent / "setup").rename(tmp_path / "unused-kit")
    if setup_kind == "finalized-base":
        folder = _finalized_base(parent / "myproj")
    else:  # a folder that happens to hold shell/finalize.sh
        folder = parent / "tools"
        (folder / "shell").mkdir(parents=True)
        shutil.copy2(FINALIZE_SH, folder / "shell" / "finalize.sh")
        (folder / "notes.txt").write_text("mine\n", encoding="utf-8")
    before = sorted(str(p.relative_to(parent)) for p in parent.rglob("*"))

    for args in ((), ("--kb-dir", str(neighbour)), ("--dry-run",), ("--resume",)):
        result = subprocess.run(
            ["bash", "shell/finalize.sh", "--no-claude-md", *args],
            cwd=folder, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
        )
        assert result.returncode == 1, (args, result.stdout + result.stderr)
        assert "not the engine kit" in result.stderr
        assert "bash setup/shell/finalize.sh" in result.stderr

    assert sorted(str(p.relative_to(parent)) for p in parent.rglob("*")) == before


def test_finalize_does_not_nest_or_move_a_base_venv(tmp_path: Path):
    """E-H8: a knowledge-base/.venv moved to the root breaks (and nested into .venv/.venv)."""
    kb = _stage_project(tmp_path)
    _venv(kb / ".venv", "base venv")
    _venv(kb / "venv", "legacy venv")

    result = _run_finalize(tmp_path, "--no-claude-md")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / ".venv").exists()
    assert not (tmp_path / "venv").exists()
    assert (kb / ".venv" / "marker").is_file()
    assert (kb / "venv" / "marker").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert "01_PREREQUISITES.md" in result.stdout


def test_finalize_copies_instruction_modules_into_kb_docs(tmp_path: Path):
    """D5 / E-H1: the modules the ! commands point at must survive setup/ removal."""
    kb = _stage_project(tmp_path)
    _setup_modules(tmp_path)
    (kb / "kb-docs").mkdir()
    (kb / "kb-docs" / "16_MERGE.md").write_text("# agent copy\n", encoding="utf-8")

    result = _run_finalize(tmp_path, "--no-claude-md")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "setup").exists()
    docs = tmp_path / "kb-docs"
    assert sorted(p.name for p in docs.iterdir()) == [
        "00_OVERVIEW.md", "16_MERGE.md", "18_HEAL.md", "README.md",
    ]
    assert (docs / "16_MERGE.md").read_text(encoding="utf-8") == "# agent copy\n"
    assert (docs / "18_HEAL.md").read_text(encoding="utf-8") == "# 18_HEAL.md (setup)\n"


def test_finalize_dry_run_reports_kb_docs_without_writing(tmp_path: Path):
    _stage_project(tmp_path)
    _setup_modules(tmp_path)
    result = _run_finalize(tmp_path, "--dry-run")
    assert result.returncode == 0
    assert "kb-docs/" in result.stdout
    assert not (tmp_path / "kb-docs").exists()
    assert not (tmp_path / ".kb-finalize.journal").exists()


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions that apply to the current user",
)
def test_finalize_partial_failure_exits_2_and_resume_completes(tmp_path: Path):
    """Q15: a failed move used to exit 1 with no way to continue."""
    kb = _stage_project(tmp_path)
    _setup_modules(tmp_path)
    locked = kb / "review"
    locked.mkdir()
    (locked / "x.md").write_text("x\n", encoding="utf-8")
    locked.chmod(0o555)  # a directory without write permission cannot be re-parented
    try:
        first = _run_finalize(tmp_path, "--keep-setup", "--no-claude-md")
        assert first.returncode == 2, first.stdout + first.stderr
        journal = tmp_path / ".kb-finalize.journal"
        assert journal.is_file()
        recorded = journal.read_text(encoding="utf-8").splitlines()
        assert f"project_root={tmp_path.resolve()}" in recorded
        assert recorded[-1] == "end=ok"
        assert not (tmp_path / ".kb-finalize.journal.tmp").exists()
        assert "--resume" in first.stderr
        assert (tmp_path / "AGENTS.md").is_file()  # moved before the failure
        assert locked.is_dir()

        again = _run_finalize(tmp_path)
        assert again.returncode == 1
        assert "--resume" in again.stderr
    finally:
        locked.chmod(0o755)

    resumed = _run_finalize(tmp_path, "--resume")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert (tmp_path / "review" / "x.md").is_file()
    assert (tmp_path / "scripts" / "kb_ingest.py").is_file()
    assert not (tmp_path / "knowledge-base").exists()
    assert not (tmp_path / ".kb-finalize.journal").exists()
    assert (tmp_path / "kb-docs" / "18_HEAL.md").is_file()
    # Options of the interrupted run are kept: --keep-setup and --no-claude-md.
    assert (tmp_path / "setup").is_dir()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_finalize_resume_without_journal_refuses(tmp_path: Path):
    _stage_project(tmp_path)
    result = _run_finalize(tmp_path, "--resume")
    assert result.returncode == 1
    assert "no interrupted run" in result.stderr
    assert (tmp_path / "knowledge-base" / "AGENTS.md").is_file()


@pytest.mark.parametrize(
    ("index_block", "args", "expected"),
    [
        ('index:\n  primary_agent: "claude-code"   # set in 02_INIT Q5\n', (), True),
        ("index:\n  primary_agent: claude-code\r\n", (), True),
        ('index:\n  # primary_agent: "claude-code"\n', (), False),
        ('index:\n  primary_agent: "codex"\n', (), False),
        ("index:\n  primary_agent: claude-code   \n", (), True),  # trailing blanks
        ("index: {primary_agent: claude-code, window_profile: 1m}\n", (), True),
        ('index: { window_profile: "1m", primary_agent: "claude-code" }  # Q5\n', (), True),
        ("index: {primary_agent: codex}\n", (), False),
        ("index:\n  primary_agent: Claude-Code\n", (), True),  # any letter case
        ('index:\n  primary_agent: "claude-code"\n', ("--no-claude-md",), False),
    ],
)
def test_finalize_claude_md_follows_primary_agent_without_a_tty(
    tmp_path: Path, index_block: str, args: tuple[str, ...], expected: bool
):
    """E Medium: a non-interactive finalize never created CLAUDE.md for Claude Code."""
    kb = _stage_project(tmp_path)
    (kb / "kb.config.yml").write_text(
        "knowledge_base:\n  name: test\n" + index_block + "status:\n  enabled: true\n",
        encoding="utf-8",
    )
    result = _run_finalize(tmp_path, *args, stdin="")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "CLAUDE.md").exists() is expected


def _journal(root: Path, **fields: str) -> Path:
    journal = root / ".kb-finalize.journal"
    journal.write_text("".join(f"{k}={v}\n" for k, v in fields.items()), encoding="utf-8")
    return journal


@pytest.mark.parametrize(
    "case",
    ["empty", "cut-short", "no-kb-dir", "kb-dir-root", "kb-dir-parent", "kb-dir-setup",
     "kb-dir-relative", "other-project", "backup-elsewhere"],
)
def test_finalize_resume_refuses_a_damaged_journal(tmp_path: Path, case: str):
    """Q15: an empty journal made --resume move /bin, /etc, ... into the project."""
    root = tmp_path / "project"
    root.mkdir()
    _stage_project(root)
    project = str(root.resolve())
    good = {
        "project_root": project,
        "kb_dir": f"{project}/knowledge-base",
        "backup_dir": f"{project}/.kb-finalize-backup/2026-09-24T10-00-00",
        "keep_setup": "false",
        "force": "false",
        "claude_md": "no",
        "end": "ok",
    }
    if case == "empty":
        journal = root / ".kb-finalize.journal"
        journal.write_text("", encoding="utf-8")
    elif case == "cut-short":
        journal = _journal(root, project_root=project, kb_dir=f"{project}/knowl")
    else:
        bad = {
            "no-kb-dir": {"kb_dir": ""},
            "kb-dir-root": {"kb_dir": "/"},
            "kb-dir-parent": {"kb_dir": str(tmp_path.resolve())},
            "kb-dir-setup": {"kb_dir": f"{project}/setup"},
            "kb-dir-relative": {"kb_dir": "knowledge-base"},
            "other-project": {"project_root": "/somewhere/else"},
            "backup-elsewhere": {"backup_dir": "/"},
        }[case]
        journal = _journal(root, **{**good, **bad})
    before = journal.read_text(encoding="utf-8")

    for args in (("--resume", "--dry-run"), ("--resume",)):
        result = _run_finalize(root, *args)
        assert result.returncode == 1, (args, result.stdout + result.stderr)
        assert "delete the journal" in result.stderr
        assert "would move" not in result.stdout
        assert "moved" not in result.stdout

    plain = _run_finalize(root)
    assert plain.returncode == 1
    assert "delete it" in plain.stderr
    assert journal.read_text(encoding="utf-8") == before
    assert (root / "knowledge-base" / "AGENTS.md").is_file()
    assert (root / "setup").is_dir()
    assert not (root / "AGENTS.md").exists()


def test_finalize_refuses_a_base_inside_setup(tmp_path: Path):
    """Q1 follow-up: `--kb-dir setup/kb` passed the guard, and the final
    rm of setup/ took the base and the .git it had "kept in place"."""
    kb = _stage_project(tmp_path)
    nested = tmp_path / "setup" / "kb"
    kb.rename(nested)
    (nested / ".git").mkdir()
    (nested / ".git" / "HEAD").write_text("base repo\n", encoding="utf-8")

    result = _run_finalize(tmp_path, "--kb-dir", "setup/kb", "--no-claude-md")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "inside" in result.stderr and "Move it out" in result.stderr
    assert (nested / ".git" / "HEAD").is_file()
    assert (nested / "AGENTS.md").is_file()
    assert not (tmp_path / "AGENTS.md").exists()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=str(repo.parent / "home"), GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          env=env, timeout=60)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_finalize_merges_gitignore_and_gitattributes_into_the_project_files(tmp_path: Path):
    """E-H3 / D2: the base's ignore rules must cover its private folders both
    before finalize (nested file) and after it (merged into the root file),
    even when the project already had its own .gitignore."""
    root = tmp_path / "project"
    root.mkdir()
    kb = _stage_project(root)
    assert _git(root, "init", "-q").returncode == 0
    (root / ".gitignore").write_text("node_modules/\n/raw/\n", encoding="utf-8")
    # No final newline; *.sh overlaps the base's `*.sh text eol=lf`.
    (root / ".gitattributes").write_text("*.sh text=auto\n*.png binary", encoding="utf-8")
    templates = REPO_ROOT / "knowledge-base" / "templates"
    shutil.copy(templates / ".gitignore.template", kb / ".gitignore")
    shutil.copy(templates / ".gitattributes.template", kb / ".gitattributes")
    private = ["raw/chats/unsorted/chat.txt", "interactions/sessions/s.md",
               "assets/documents/a.pdf", "review/needs-redaction/r.md"]
    for rel in private:
        (kb / rel).parent.mkdir(parents=True, exist_ok=True)
        (kb / rel).write_text("ghp_secret\n", encoding="utf-8")

    staged = _git(root, "add", "-A", "--dry-run").stdout
    assert not [rel for rel in private if rel in staged], staged

    dry = _run_finalize(root, "--dry-run")
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "would add to ./.gitignore (at the top)" in dry.stdout
    assert (root / ".gitignore").read_text(encoding="utf-8") == "node_modules/\n/raw/\n"

    result = _run_finalize(root, "--no-claude-md")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "merged knowledge-base/.gitignore" in result.stdout
    assert not (root / "knowledge-base").exists()
    ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    # The project's own rules stay verbatim and come last, so they keep precedence.
    assert ignore[-2:] == ["node_modules/", "/raw/"]
    assert ignore.count("/raw/") == 1 and "/interactions/" in ignore
    staged = _git(root, "add", "-A", "--dry-run").stdout
    assert not [rel for rel in private if rel in staged], staged
    attrs = (root / ".gitattributes").read_text(encoding="utf-8")
    assert attrs.endswith("\n\n*.sh text=auto\n*.png binary")
    # Minor (review): the base's catch-all `* text=auto` came after the project's
    # rules and overrode them; it is left out, and project rules win.
    assert "* text=auto" not in attrs.splitlines()
    check = _git(root, "check-attr", "text", "eol", "--",
                 "shell/lint.sh", "reindex.bat", "notes.txt").stdout.splitlines()
    assert "shell/lint.sh: text: auto" in check          # the project's rule wins
    assert "shell/lint.sh: eol: lf" in check and "reindex.bat: eol: crlf" in check
    assert "notes.txt: text: unspecified" in check        # no new catch-all


def test_finalize_treats_a_symlinked_project_gitignore_as_a_conflict(tmp_path: Path):
    """The merge rewrites the project file; a symlink would be replaced by a copy."""
    kb = _stage_project(tmp_path)
    (kb / ".gitignore").write_text("/raw/\n", encoding="utf-8")
    (tmp_path / "shared.gitignore").write_text("node_modules/\n", encoding="utf-8")
    try:
        (tmp_path / ".gitignore").symlink_to("shared.gitignore")
    except OSError:
        pytest.skip("symlinks not available")
    result = _run_finalize(tmp_path, "--no-claude-md")
    assert result.returncode == 1
    assert "- .gitignore" in result.stderr
    assert (tmp_path / "shared.gitignore").read_text(encoding="utf-8") == "node_modules/\n"
