"""The deployment docs (00/01/02, knowledge-base/README.md) must match the kit.

The e2e audit followed 02_INIT.md literally from a project root and hit paths
that do not exist there, a `mode:` value no script accepts, a frontmatter
example that lint rejects, and links that break once the kit is copied as
setup/. These tests run the documented commands the way an agent would.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
KIT = REPO_ROOT / "knowledge-base"
SCRIPTS = KIT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kb_common as kbc  # noqa: E402
import kb_lint  # noqa: E402
import kb_populate  # noqa: E402

DOCS = {name: (KIT / name).read_text(encoding="utf-8")
        for name in ("00_OVERVIEW.md", "01_PREREQUISITES.md", "02_INIT.md", "README.md")}
ROLE = "programmer-senior"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = re.search(r"^#{2,3} ", text[start + len(heading):], re.M)
    return text[start:start + len(heading) + (nxt.start() if nxt else len(text))]


def _fenced(text: str, lang: str) -> list[str]:
    return re.findall(rf"^```{lang}\n(.*?)^```", text, re.M | re.S)


def _bash_ok() -> bool:
    try:
        return subprocess.run(["bash", "-c", "true"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _py(project: Path, command: str) -> subprocess.CompletedProcess:
    """Run a documented `python3 …` command from the project root."""
    assert command.startswith("python3 ")
    args = command.split()[1:]
    return subprocess.run([sys.executable, *args], cwd=project, capture_output=True,
                          text=True, timeout=120)


def test_02_runs_kit_scripts_by_their_path_from_the_project_root():
    """E: `python3 scripts/kb_structure.py` failed — scripts live in setup/ at that point."""
    text = DOCS["02_INIT.md"]
    assert not re.search(r"python3 scripts/", text)
    for folder, name in re.findall(r"python3 (setup|knowledge-base)/scripts/(\w+\.py)", text):
        assert (SCRIPTS / name).is_file(), f"{folder}/scripts/{name}"


@pytest.mark.skipif(not _bash_ok() or sys.platform == "win32", reason="needs a POSIX bash")
def test_02_phase0_and_phase1_commands_work_as_written(tmp_path: Path):
    project = tmp_path / "my-project"
    shutil.copytree(KIT, project / "setup",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    text = DOCS["02_INIT.md"]
    commands = [
        "python3 setup/scripts/kb_common.py --version",
        f"python3 setup/scripts/kb_structure.py --role {ROLE} --blind-spots",
        f"python3 setup/scripts/kb_structure.py --role {ROLE} --write --kb-root knowledge-base",
    ]
    for command in commands:
        assert command.replace(ROLE, "<slug>") in text, command
        result = _py(project, command)
        assert result.returncode == 0, command + "\n" + result.stderr
    assert _py(project, commands[0]).stdout.strip() == kbc.ENGINE_VERSION
    assert (project / "knowledge-base" / "interactions" / "init" / "STRUCTURE_VARIANTS.md").is_file()

    copy_block = _fenced(_section(text, "### Copy the engine files"), "bash")[0]
    copied = subprocess.run(["bash", "-euc", copy_block], cwd=project, capture_output=True,
                            text=True, timeout=120)
    assert copied.returncode == 0, copied.stderr
    base = project / "knowledge-base"
    assert not (base / "scripts" / "tests").exists()
    assert not list(base.rglob("__pycache__"))
    assert (base / "kb-docs" / "18_HEAL.md").is_file()
    assert (base / "kb-docs" / "README.md").is_file()
    assert (base / ".gitattributes").is_file() and (base / ".gitignore").is_file()
    assert (base / "shell" / "install-hooks.sh").is_file()
    assert (base / "requirements.txt").is_file()

    init = "python3 knowledge-base/scripts/kb_ingest.py --init-dirs --root knowledge-base"
    assert init in text
    assert _py(project, init).returncode == 0
    assert (base / "raw" / "work" / "unsorted").is_dir()

    # Phase 2: the documented --entities-from command fills `entities: {}`.
    shutil.copy(project / "setup" / "templates" / "kb.config.yml.template",
                base / "kb.config.yml")
    entities = (f"python3 knowledge-base/scripts/kb_populate.py --entities-from {ROLE} "
                "--kb-root knowledge-base")
    assert entities.replace(ROLE, "<slug>") in _section(text, "## Phase 2")
    result = _py(project, entities)
    assert result.returncode == 0, result.stderr
    config = yaml.safe_load((base / "kb.config.yml").read_text(encoding="utf-8"))
    role = yaml.safe_load((KIT / "examples" / f"{ROLE}.yml").read_text(encoding="utf-8"))
    assert list(config["entities"]) == list(role["entities"])


def test_02_creates_the_base_gitignore_even_when_the_project_has_one():
    """E-H3 (review): 02 told the agent to append the template to an existing root
    .gitignore instead; its anchored patterns (/raw/, /interactions/) then missed
    knowledge-base/raw/ etc. for the whole build, and `git add -A` staged them.
    The behaviour itself: test_finalize_sh.py::test_finalize_merges_gitignore_…"""
    text = DOCS["02_INIT.md"]
    section = _section(text, "### Copy the engine files")
    assert "append the template's lines to the root file" not in text
    assert "even when the project root already has" in section
    block = _fenced(section, "bash")[0]
    assert "cp setup/templates/.gitignore.template knowledge-base/.gitignore" in block
    assert "cp setup/templates/.gitattributes.template knowledge-base/.gitattributes" in block
    assert "post-commit.local" not in text  # the hook has no such mechanism


def test_02_role_menu_language_and_tree_match_the_kit():
    """I-LOW: PM/founder/researcher were offered as roles "not in the templates"
    although examples/ has them, and the tree still showed setup/, which finalize
    removes. E: the language of the generated files was never set."""
    text = DOCS["02_INIT.md"]
    menu = _section(text, "### When the user did NOT specify a role")
    assert "**every** `setup/examples/*.yml`" in menu
    assert "Or I can suggest" not in menu
    assert "knowledge_base.language" in text[:text.index("## Deployment flow")]
    tree = _fenced(_section(text, "### Create the folders"), "text")[0]
    assert "setup/" not in tree and "kb-docs/" in tree


def test_02_config_example_uses_a_valid_mode():
    """I14: the example set `mode: "local-first"`, which no script accepts."""
    block = _fenced(_section(DOCS["02_INIT.md"], "### Example values for a hybrid role"), "yaml")[0]
    data = yaml.safe_load(block)
    assert data["knowledge_base"]["mode"] in ("default", "super")
    assert "mode" not in data


def test_02_frontmatter_example_passes_the_required_fields_check():
    """I-LOW: the example had no `lifecycle`, which kb_lint requires."""
    block = _fenced(_section(DOCS["02_INIT.md"], "## Frontmatter metadata"), "markdown")[0]
    meta, _ = kbc.parse_frontmatter(block)
    assert set(kb_lint.REQUIRED_FRONTMATTER_FIELDS) <= set(meta)
    assert meta["lifecycle"] in kbc.LIFECYCLES


def test_02_finishes_only_after_modules_03_to_18():
    """E: Phase 3 sent the agent to doctor + finalize before modules 03–13 and 15–18."""
    text = DOCS["02_INIT.md"]
    phase3 = text.index("## Phase 3")
    finish = text.index("## Finish the deployment")
    assert phase3 < finish
    assert "finalize.sh --resume" in text[finish:]
    assert "--claude-md" in text[finish:]  # the non-interactive CLAUDE.md choice
    assert "bash setup/shell/finalize.sh" not in text[:finish].split("## Phase 0")[1]
    assert "18_HEAL.md" in text[:text.index("## Phase 0")]  # module list is 00 … 18


def test_deploy_docs_do_not_point_at_a_monolithic_index():
    """Packs replaced .repomix/output.xml; the docs still sent agents there."""
    for name, text in DOCS.items():
        assert ".repomix/output.xml" not in text, name


def test_versions_come_from_kb_common_not_a_missing_version_file():
    """E: `{{KB_INSTRUCTIONS_VERSION}}` was "populated from repo VERSION" — absent in setup/."""
    for name in ("00_OVERVIEW.md", "02_INIT.md"):
        assert "kb_common.py --version" in DOCS[name], name


def test_doctor_pass_means_exit_0():
    """E: "when kb_doctor passes" was never defined (doctor exits 1 on warnings alone)."""
    for name in ("00_OVERVIEW.md", "01_PREREQUISITES.md", "02_INIT.md"):
        assert re.search(r"passes when it exits 0", DOCS[name]), name


def test_00_mental_model_sends_simple_files_to_extraction():
    """I1: "On simple files, no review" — processed/ files were never extracted."""
    model = _section(DOCS["00_OVERVIEW.md"], "## Quick mental model")
    assert "extraction: pending" in model and "!review" in model
    assert "no review" not in model


def test_readme_quick_start_matches_the_setup_flow():
    """E: README said "copy as knowledge-base/"; 00/02 and the root README say setup/."""
    quick = _section(DOCS["README.md"], "## Quick start for the user")
    assert "renamed to setup/" in quick
    assert "setup/00_OVERVIEW.md" in quick and "finalize.sh" in quick


def test_01_puts_the_venv_at_the_project_root_with_install_hints():
    text = DOCS["01_PREREQUISITES.md"]
    assert "RTF" in text                                  # striprtf was missing from the list
    assert "venv at the base root" not in text.lower()
    assert "project root" in _section(text, "## Python virtual environment")
    assert "python3-venv" in text                         # ensurepip missing on Debian/Ubuntu
    assert "nltk.downloader stopwords punkt" in text      # RAKE finds nothing without it
    assert "requirements-nlp.txt" in text and "download.pytorch.org/whl/cpu" in text
    assert "npx --yes repomix@" in text                   # the pinned fallback, not @latest
    assert "repomix@latest" not in text


def test_readme_links_survive_being_copied_as_setup_or_kb_docs():
    """E: `../i18n/…` broke once the kit was copied into a project as setup/."""
    assert "](../" not in DOCS["README.md"]


def test_readme_lists_every_command_of_the_agents_template():
    """I13: !export/!import/!merge (and later additions) were missing from the README."""
    template = (KIT / "templates" / "AGENTS.md.template").read_text(encoding="utf-8")
    table = _section(DOCS["README.md"], "## User commands")
    names = set(re.findall(r"^\| `(![a-z-]+)", template, re.M))
    assert names
    assert names <= set(re.findall(r"`(![a-z-]+)", table))
    for command in ("!status", "!meta-review", "!export", "!import", "!merge"):
        assert f"`{command}`" in table


def test_readme_marks_unimplemented_automation():
    """I5: the trigger table claimed an AI surprise filter and auto-processed queues."""
    table = _section(DOCS["README.md"], "### What runs automatically, and who does it")
    surprise = next(line for line in table.splitlines() if line.startswith("| Surprise filter"))
    assert "not implemented yet" in surprise
    assert "Auto-processed" not in table


def test_readme_status_runs_kb_status():
    """Residual I13/D4: README said `!status` only reads STATUS.md; it runs kb_status.py."""
    line = next(line for line in DOCS["README.md"].splitlines() if line.startswith("- **`!status`**"))
    assert "python3 scripts/kb_status.py" in line
    assert "only reads" not in line


def test_02_tree_and_placeholders_match_the_kit():
    """Residual e2e: the tree missed folders --init-dirs creates, and Phase 2
    did not list the {{SPACY_MODEL}} placeholder of the config template."""
    text = DOCS["02_INIT.md"]
    tree = _fenced(_section(text, "### Create the folders"), "text")[0]

    def block(folder: str) -> str:
        start = tree.index(f"├── {folder}/")
        return tree[start:tree.index("\n├── ", start + 1)]

    for group, names in (("raw", kbc.RAW_DIRS), ("processed", kbc.PROCESSED_DIRS),
                         ("knowledge", kbc.KNOWLEDGE_DIRS)):
        for name in names:
            if (group, name) != ("raw", "unsorted"):  # raw/unsorted/ is named in the raw/ line
                assert f"{name}/" in block(group), f"{group}/{name}/"
    template = (KIT / "templates" / "kb.config.yml.template").read_text(encoding="utf-8")
    phase2 = _section(text, "## Phase 2")
    for placeholder in set(re.findall(r"\{\{[A-Z_]+\}\}", template)):
        assert placeholder in phase2, placeholder


def test_deployed_config_stays_small(tmp_path: Path):
    """Residual budget: the agent reads kb.config.yml at every session start.
    The config template's long comments moved into kb-docs/ modules; keep a
    deployed config (template + a role's entities) under 10 KB."""
    template = KIT / "templates" / "kb.config.yml.template"
    roles = sorted((KIT / "examples").glob("*.yml"))
    assert roles
    for role in roles:
        if not (yaml.safe_load(role.read_text(encoding="utf-8")) or {}).get("entities"):
            continue
        base = tmp_path / role.stem
        base.mkdir()
        shutil.copyfile(template, base / "kb.config.yml")
        assert kb_populate.main(["--entities-from", role.stem, "--kb-root", str(base)]) == 0
        size = (base / "kb.config.yml").stat().st_size
        assert size <= 10 * 1024, f"{role.name}: deployed kb.config.yml is {size} bytes"


# Deploy-time reading: modules the deploying agent reads in full (02 Phase 3).
DEPLOY_READ_BUDGET = 182_000
# README + every module, all copied into kb-docs/. A soft ceiling: raise it on
# purpose when a module has to grow, not by accident.
MODULES_BUDGET = 282_000


def test_02_phase3_splits_modules_into_deploy_and_runtime_reading():
    """Residual budget: the deploying agent read README + 00–18 in full (~83K tokens)."""
    phase3 = _section(DOCS["02_INIT.md"], "## Phase 3")
    flat = " ".join(phase3.split())
    full = re.search(r"Read in full the modules that set the base up now: ([\d, ]+)\.", flat)
    assert full
    deploy = {n.strip() for n in full.group(1).split(",")}
    runtime = set(re.findall(r"^- (\d\d) — ", phase3, re.M))
    assert deploy.isdisjoint(runtime)
    assert deploy | runtime == {f"{n:02d}" for n in range(3, 19)}
    read = [KIT / "README.md"] + [
        path for path in sorted(KIT.glob("[0-9][0-9]_*.md"))
        if path.name[:2] in deploy | {"00", "01", "02"}
    ]
    deploy_bytes = sum(path.stat().st_size for path in read)
    assert deploy_bytes <= DEPLOY_READ_BUDGET, deploy_bytes
    total = sum(path.stat().st_size for path in [KIT / "README.md", *KIT.glob("[0-9][0-9]_*.md")])
    assert total <= MODULES_BUDGET, total
