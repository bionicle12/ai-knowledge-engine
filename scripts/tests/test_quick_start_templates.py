"""Lite mode: the quick-start templates and INIT_GUIDE.md say what the scripts do."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
QUICK_START = REPO_ROOT / "quick-start"
TEMPLATES = QUICK_START / "templates"
GUIDE = (QUICK_START / "INIT_GUIDE.md").read_text(encoding="utf-8")

# Secret-file ignores in forms repomix 1.14.0 applies next to an include list
# ('**/.env*' and '**/id_rsa*' are silently dropped there).
SECRET_PATTERNS = ["**/.env", "**/**/.env.*", "**/*.env", "**/*.pem", "**/*.key", "**/*.p12",
                   "**/*.pfx", "**/*.jks", "**/*.keystore", "**/**/id_rsa*", "**/**/id_ecdsa*",
                   "**/**/id_ed25519*"]


def _agents_block() -> str:
    text = (TEMPLATES / "AGENTS_SECTION.md").read_text(encoding="utf-8")
    return text.split("\n---\n", 1)[1]


# ---------------------------------------------------------------------------
# A1: no token numbers where they rot; the OVER rule reaches the agent
# ---------------------------------------------------------------------------
def test_agents_section_has_no_token_numbers_and_the_over_rule() -> None:
    block = _agents_block()
    assert "Tokens" not in block
    assert not re.search(r"~\s*\d+\s*K\b", block)
    assert "PACKS_STATUS.md" in block
    assert re.search(r"\*\*OVER\*\*.*never loaded\s+whole", block, re.S)
    assert len(block.strip().splitlines()) <= 45


def test_manifest_example_carries_no_token_counts() -> None:
    manifest = json.loads((TEMPLATES / "repomix.packs.json.example").read_text(encoding="utf-8"))
    assert all("approx_tokens" not in pack for pack in manifest["packs"])
    assert manifest["repomix_version"] == "1.14.0"
    assert isinstance(manifest["coverage_ignore"], list)


# ---------------------------------------------------------------------------
# A7: templates keep secrets out, in forms repomix really applies
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["catalog.json.example", "domain-pack.json.example"])
def test_pack_configs_exclude_secret_files(name: str) -> None:
    config = json.loads((TEMPLATES / "configs" / name).read_text(encoding="utf-8"))
    patterns = config["ignore"]["customPatterns"]
    assert [p for p in SECRET_PATTERNS if p not in patterns] == []
    assert config["security"]["enableSecurityCheck"] is True


def _repomix_1_14() -> str | None:
    exe = shutil.which("repomix")
    if not exe or os.name == "nt":
        return None
    try:
        version = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return exe if version.strip() == "1.14.0" else None


def test_secret_patterns_work_on_repomix_1_14(tmp_path: Path) -> None:
    exe = _repomix_1_14()
    if not exe:
        pytest.skip("repomix 1.14.0 is not installed")
    for rel in ("src/.env", "src/.env.dev", "src/a/.env.local", "src/a/aws.env", "src/a/cert.pem",
                "src/a/tls.key", "src/a/store.p12", "src/a/id_rsa", "src/a/keep.txt"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")
    config = json.loads((TEMPLATES / "configs" / "domain-pack.json.example").read_text(encoding="utf-8"))
    config["include"] = ["src/**"]
    config["output"]["filePath"] = "out.xml"
    config["security"]["enableSecurityCheck"] = False
    (tmp_path / "pack.json").write_text(json.dumps(config), encoding="utf-8")
    subprocess.run([exe, "-c", "pack.json", "--quiet"], cwd=tmp_path, check=True, timeout=120,
                   env={**os.environ, "HOME": str(tmp_path)})
    packed = re.findall(r'^<file path="([^"]+)">', (tmp_path / "out.xml").read_text(encoding="utf-8"), re.M)
    assert packed == ["src/a/keep.txt"]


# ---------------------------------------------------------------------------
# A13: Windows wrappers, line endings, copy destinations
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["update-repomix-index.bat", "install-git-hooks.bat"])
def test_bat_wrappers_prefer_git_for_windows_bash_over_wsl(name: str) -> None:
    text = (TEMPLATES / "scripts" / name).read_text(encoding="utf-8")
    assert text.index(r"%ProgramFiles%\Git\bin\bash.exe") < text.index("'where bash")
    assert text.index("'where git") < text.index("'where bash")
    assert 'findstr /i /c:"System32" /c:"WindowsApps"' in text
    assert "\nwhere bash >nul" not in text  # the old first probe


def test_template_line_endings_are_pinned() -> None:
    if not shutil.which("git"):
        pytest.skip("needs git")
    paths = ["quick-start/templates/githooks/pre-push", "quick-start/templates/githooks/post-checkout",
             "quick-start/templates/scripts/update-repomix-index.sh",
             "quick-start/templates/scripts/install-git-hooks.bat"]
    out = subprocess.run(["git", "check-attr", "eol", "--", *paths], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True).stdout
    assert out.splitlines() == [
        f"{paths[0]}: eol: lf", f"{paths[1]}: eol: lf", f"{paths[2]}: eol: lf", f"{paths[3]}: eol: crlf",
    ]
    assert ".githooks/* text eol=lf" in GUIDE


def test_guide_maps_every_template_to_an_explicit_destination() -> None:
    table = GUIDE[GUIDE.index("| From `<engine>/quick-start/templates/` |"):]
    table = table[:table.index("\n\n")]
    for template in sorted(p.relative_to(TEMPLATES).as_posix() for p in TEMPLATES.rglob("*") if p.is_file()):
        name = template.rsplit("/", 1)[-1]
        stem = name.removesuffix(".example").removesuffix(".json").removesuffix(".sh").removesuffix(".bat")
        assert stem in table, template
    assert "Never copy the\n`templates/` folder itself" in GUIDE


# ---------------------------------------------------------------------------
# The guide describes the behaviour the scripts have now
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("needle", [
    "--check", "coverage_ignore", "post-checkout", ".githooks/<hook>.local", "core.hooksPath",
    "repomix_version", "FAILED (old copy)", ".repomix/coverage.txt", "--no-wait",
])
def test_guide_documents_the_script_behaviour(needle: str) -> None:
    assert needle in GUIDE
    scripts = (TEMPLATES / "scripts" / "update-repomix-index.sh").read_text(encoding="utf-8") + \
        (TEMPLATES / "scripts" / "install-git-hooks.sh").read_text(encoding="utf-8") + \
        "".join(p.read_text(encoding="utf-8") for p in (TEMPLATES / "githooks").iterdir()) + \
        (TEMPLATES / "repomix.packs.json.example").read_text(encoding="utf-8")
    assert needle.replace("<hook>", "pre-push") in scripts


def test_guide_no_longer_promises_mtime_only_freshness() -> None:
    assert "(mtime comparison)" not in GUIDE
    assert "It's a dozen lines of script." not in GUIDE  # the coverage check is built in now


def test_readme_names_every_git_event_the_lite_hooks_cover() -> None:
    """The README said "commit/push/pull"; Lite also refreshes after a rebase
    (post-rewrite) and a branch checkout (post-checkout)."""
    installer = (TEMPLATES / "scripts" / "install-git-hooks.sh").read_text(encoding="utf-8")
    hooks = set(re.search(r'^HOOKS="([^"]+)"', installer, re.M).group(1).split())
    assert hooks == {p.name for p in (TEMPLATES / "githooks").iterdir()}
    events = {"post-commit": "commit", "pre-push": "push", "post-merge": "pull/merge",
              "post-rewrite": "rebase", "post-checkout": "branch checkout"}
    assert hooks == set(events)
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "commit/push/pull" not in readme
    lite_row = next(line for line in readme.splitlines() if line.startswith("| You get |"))
    for event in events.values():
        assert event in lite_row, event


def test_readme_describes_what_the_lite_index_script_does() -> None:
    """The README promised only "fresh sizes" and `--force`; the script also
    flags OVER/FAILED packs and coverage problems, locks, and has `--check`."""
    readme = " ".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").split())
    script = (TEMPLATES / "scripts" / "update-repomix-index.sh").read_text(encoding="utf-8")
    assert "fresh sizes in `.repomix/PACKS_STATUS.md`" not in readme
    assert "OVER/FAILED flags and coverage problems in `.repomix/PACKS_STATUS.md`" in readme
    assert "`--check` to only refresh `PACKS_STATUS.md`" in readme
    assert "PATH bootstrap, locking and logging" in readme
    assert "--check)" in script and "LOCK_DIR=" in script
