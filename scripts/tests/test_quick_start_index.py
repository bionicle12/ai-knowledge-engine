"""Lite mode: quick-start/templates/scripts/update-repomix-index.sh.

Every test builds a throwaway git project from the templates and runs the real
script with a fake `repomix` (a small Python program that packs the included
files into the same XML shape and prints the same summary lines as repomix
1.14), so the tests need sh, git and node but no network and no real repomix.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
QUICK_START = REPO_ROOT / "quick-start"
SCRIPT = QUICK_START / "templates" / "scripts" / "update-repomix-index.sh"

pytestmark = [
    pytest.mark.skipif(os.name == "nt", reason="POSIX shell script"),
    pytest.mark.skipif(
        not (shutil.which("git") and shutil.which("node") and Path("/bin/sh").exists()),
        reason="needs git, node and /bin/sh",
    ),
    pytest.mark.skipif(
        any(Path(d, "repomix").exists() for d in ("/usr/local/bin", "/opt/homebrew/bin")),
        reason="the script puts /usr/local/bin and /opt/homebrew/bin first; a real repomix there would shadow the fake",
    ),
]

FAKE_REPOMIX = r'''#!{python}
"""Stands in for repomix 1.14: same XML shape, same summary lines."""
import fnmatch, json, os, sys, time
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["FAKE_REPOMIX_CALLS"], "a", encoding="utf-8") as f:
    f.write(" ".join(args) + "\n")
if "--version" in args:
    print(os.environ.get("FAKE_REPOMIX_VERSION", "1.14.0"))
    sys.exit(0)
cfg_path = args[args.index("-c") + 1] if "-c" in args else "repomix.config.json"
try:
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
except Exception as exc:
    print(f"Error: cannot read {cfg_path}: {exc}", file=sys.stderr)
    sys.exit(2)
if cfg.get("fail"):
    print("Error: boom from fake repomix", file=sys.stderr)
    sys.exit(int(cfg["fail"]))
time.sleep(float(os.environ.get("FAKE_REPOMIX_SLEEP", "0")))
out = cfg.get("output", {}).get("filePath", "repomix-output.xml")
ignore = cfg.get("ignore", {}).get("customPatterns", [])
files = set()
for inc in cfg.get("include", ["**"]):
    base = inc.split("*")[0].rstrip("/") or "."
    if os.path.isfile(base):
        files.add(base)
        continue
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".repomix")]
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name)).replace(os.sep, "/")
            if fnmatch.fnmatch(rel, inc) and not any(fnmatch.fnmatch(rel, p) for p in ignore):
                files.add(rel)
files = sorted(files)
suspicious = [f for f in files if "SUSPICIOUS" in Path(f).read_text(errors="replace")]
parts = ["This file is a merged representation of a subset of the codebase, "
         "combined into a single document by Repomix.", "", "<files>"]
if cfg.get("output", {}).get("files", True):
    for f in files:
        if f not in suspicious:
            parts += [f'<file path="{f}">', Path(f).read_text(errors="replace").rstrip("\n"), "</file>", ""]
parts.append("</files>")
text = "\n".join(parts) + "\n" + "x" * int(cfg.get("pad", 0)) + "\n"
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text(text, encoding="utf-8")
if "--quiet" in args:
    sys.exit(0)
print("\r\x1b[K\x1b[?25l- Processing file... (1/1)")
print("Security Check:")
if suspicious:
    print(f"{len(suspicious)} suspicious file(s) detected and excluded from the output:")
    for i, f in enumerate(suspicious, 1):
        print(f"{i}. {f}")
        print("   - 1 security issue detected")
else:
    print("No suspicious files detected.")
print("")
print("Pack Summary:")
print(" Total Tokens: " + f"{len(text) // 4:,}".replace(",", " ") + " tokens")
'''

FAKE_NPX = r'''#!{python}
"""npx stand-in: records the call, then runs the fake repomix."""
import os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_NPX_CALLS"], "a", encoding="utf-8") as f:
    f.write(" ".join(args) + "\n")
rest = [a for a in args if a != "--yes"]
os.execv(os.environ["FAKE_REPOMIX_BIN"], [os.environ["FAKE_REPOMIX_BIN"]] + rest[1:])
'''

# Tools the script needs; used to build a PATH without flock.
TOOLS = (
    "awk basename cat cksum cmp comm cut date diff dirname find git grep head kill ls mkdir mktemp "
    "mv nohup od rm rmdir sed sh sleep sort tail tee timeout touch tr uniq wc"
).split()

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


class Project:
    def __init__(self, root: Path, env: dict[str, str]) -> None:
        self.root = root
        self.env = env
        self.repomix = root / ".repomix"

    # -- running ---------------------------------------------------------
    def run(self, *args: str, cwd: Path | None = None, timeout: float = 60,
            script: str | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["sh", script or str(self.root / "scripts" / "update-repomix-index.sh"), *args],
            cwd=cwd or self.root, env=env or self.env, capture_output=True, text=True, timeout=timeout,
        )

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def commit(self, message: str = "change") -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)

    # -- files -----------------------------------------------------------
    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def status(self) -> str:
        return (self.repomix / "PACKS_STATUS.md").read_text(encoding="utf-8")

    def log(self) -> str:
        path = self.repomix / "update.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def row(self, name: str) -> list[str]:
        for line in self.status().splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0] == name:
                return cells
        raise AssertionError(f"no row for {name!r} in PACKS_STATUS.md:\n{self.status()}")

    def calls(self) -> list[str]:
        path = Path(self.env["FAKE_REPOMIX_CALLS"])
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def builds(self) -> list[str]:
        return [c for c in self.calls() if "-c" in c.split()]

    def set_manifest(self, packs: list[dict], **extra) -> None:
        manifest = {"version": 1, "pack_token_ceiling": extra.pop("ceiling", 80000), **extra, "packs": []}
        for pack in packs:
            name = pack["name"]
            config = {
                "output": {"filePath": f".repomix/{name}.xml", "style": "xml", **pack.get("output", {})},
                "include": pack.get("include", []),
                "ignore": {"useGitignore": True, "customPatterns": pack.get("ignore", [])},
            }
            for key in ("fail", "pad"):
                if key in pack:
                    config[key] = pack[key]
            self.write(f".repomix/configs/{name}.json", json.dumps(config, indent=2))
            manifest["packs"].append({
                "name": name,
                "output": f".repomix/{name}.xml",
                "config": f".repomix/configs/{name}.json",
                "watch": pack.get("watch", []),
            })
        self.write("repomix.packs.json", json.dumps(manifest, indent=2))


def _write_exe(path: Path, text: str) -> None:
    path.write_text(text.replace("{python}", sys.executable), encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / SCRIPT.name)
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    _write_exe(fakebin / "repomix", FAKE_REPOMIX)
    for tool in ("node", "git"):
        (fakebin / tool).symlink_to(shutil.which(tool))
    home = tmp_path / "home"
    home.mkdir()
    env = {
        **GIT_ENV,
        "PATH": f"{fakebin}:/usr/bin:/bin",
        "HOME": str(home),
        "NVM_DIR": str(tmp_path / "no-nvm"),
        "TMPDIR": str(tmp_path),
        "FAKE_REPOMIX_CALLS": str(tmp_path / "repomix-calls.txt"),
        "FAKE_REPOMIX_BIN": str(fakebin / "repomix"),
        "LANG": "C.UTF-8",
    }
    proj = Project(root, env)
    proj.git("init", "-q")
    proj.write(".gitignore", ".repomix/*\n!.repomix/configs/\n")
    return proj


def _standard(project: Project, **extra) -> None:
    """catalog (no file bodies) + one `app` domain pack over src/app."""
    project.write("src/app/a.txt", "alpha\n")
    project.write("src/app/b.txt", "beta\n")
    project.set_manifest([
        {"name": "catalog", "include": ["src/**"], "watch": ["src"], "output": {"files": False}},
        {"name": "app", "include": ["src/app/**"], "watch": ["src/app"], **extra},
    ])
    project.commit("init")


def _packed_paths(project: Project, name: str) -> list[str]:
    text = (project.repomix / f"{name}.xml").read_text(encoding="utf-8")
    return [line[len('<file path="'):-2] for line in text.splitlines() if line.startswith('<file path="')]


# ---------------------------------------------------------------------------
# A1: the ceiling signal reaches PACKS_STATUS.md for every pack, every run
# ---------------------------------------------------------------------------
def test_fresh_pack_over_ceiling_stays_flagged(project: Project) -> None:
    _standard(project, pad=4000)
    manifest = json.loads((project.root / "repomix.packs.json").read_text())
    manifest["pack_token_ceiling"] = 500
    project.write("repomix.packs.json", json.dumps(manifest))
    project.commit("ceiling")

    first = project.run()
    assert first.returncode == 0, first.stderr
    assert project.row("app")[2:4] == ["OVER", "rebuilt"]
    builds = len(project.builds())

    second = project.run()
    assert second.returncode == 0
    assert len(project.builds()) == builds  # nothing rebuilt
    tokens, ceiling, state = project.row("app")[1:4]
    assert (ceiling, state) == ("OVER", "fresh")
    assert int(tokens) > 500  # the count repomix reported at build time
    assert "OVER the 500-token ceiling: app" in project.status()
    assert project.row("catalog")[2] == "ok"


def test_status_names_build_time_head_and_repomix_version(project: Project) -> None:
    _standard(project)
    project.run()
    head = project.git("rev-parse", "--short", "HEAD").strip()
    status = project.status()
    assert f"(HEAD {head}, repomix 1.14.0)" in status
    assert project.row("app")[4][:4].isdigit()  # "Built" column: YYYY-MM-DD HH:MM
    assert "All packs fresh and under the ceiling" in status


# ---------------------------------------------------------------------------
# A2: freshness by content, not by mtime of the files that still exist
# ---------------------------------------------------------------------------
def test_deleted_file_rebuilds_the_pack(project: Project) -> None:
    _standard(project)
    project.run()
    assert "src/app/b.txt" in _packed_paths(project, "app")

    project.git("rm", "-q", "src/app/b.txt")
    project.commit("delete b")
    project.run()

    assert project.row("app")[3] == "rebuilt"
    assert _packed_paths(project, "app") == ["src/app/a.txt"]


def test_renamed_file_rebuilds_the_pack(project: Project) -> None:
    _standard(project)
    project.run()
    project.git("mv", "src/app/a.txt", "src/app/renamed.txt")  # rename keeps the mtime
    project.commit("rename")
    project.run()
    assert _packed_paths(project, "app") == ["src/app/b.txt", "src/app/renamed.txt"]


def test_unstaged_deletion_rebuilds_the_pack(project: Project) -> None:
    _standard(project)
    project.run()
    (project.root / "src/app/b.txt").unlink()
    project.run()
    assert _packed_paths(project, "app") == ["src/app/a.txt"]


def test_config_edit_rebuilds_only_that_pack(project: Project) -> None:
    _standard(project)
    project.run()
    before = len(project.builds())
    cfg = project.root / ".repomix/configs/app.json"
    data = json.loads(cfg.read_text())
    data["ignore"]["customPatterns"] = ["src/app/b.txt"]
    cfg.write_text(json.dumps(data))
    project.run()
    assert project.builds()[before:] == ["-c .repomix/configs/app.json"]
    assert _packed_paths(project, "app") == ["src/app/a.txt"]


def test_missing_watch_path_is_reported(project: Project) -> None:
    project.write("docs/plan/08.cx/plan.md", "plan\n")
    project.set_manifest([
        {"name": "plans", "include": ["docs/plan/**"], "watch": ["docs/plan/08."]},
    ])
    project.commit("init")
    project.run()
    status = project.status()
    assert "watch path `docs/plan/08.` does not exist" in status
    assert "## Problems" in status


# ---------------------------------------------------------------------------
# A3: coverage (files in no pack / in two packs) on every run
# ---------------------------------------------------------------------------
def test_coverage_reports_orphans_and_duplicates(project: Project) -> None:
    project.write("src/a/one.txt", "1\n")
    project.write("src/a/shared.txt", "s\n")
    project.write("src/b/two.txt", "2\n")
    project.write("src/c/lost.txt", "lost\n")
    project.write("src/c/lost2.txt", "lost\n")
    project.write("src/img.bin", "\0\1binary")
    project.write("AGENTS.md", "# agents\n")
    project.write("src/.env", "APP_ENV=dev\n")  # committed, excluded from packs on purpose
    project.write("src/a/tls.pem", "cert\n")
    project.set_manifest([
        {"name": "catalog", "include": ["**"], "watch": ["src", "AGENTS.md"], "output": {"files": False}},
        {"name": "a", "include": ["src/a/**"], "watch": ["src/a"]},
        {"name": "b", "include": ["src/b/**", "src/a/shared.txt"], "watch": ["src/b", "src/a/shared.txt"]},
    ])
    project.commit("init")

    project.run()
    status = project.status()
    assert "2 file(s) under the watch paths are in no pack (top folders: src/c (2))" in status
    assert "1 file(s) are in two or more packs (e.g. src/a/shared.txt: a b)" in status
    coverage = (project.repomix / "coverage.txt").read_text(encoding="utf-8")
    assert "src/c/lost.txt" in coverage and "src/c/lost2.txt" in coverage
    for never_packed in ("AGENTS.md", "img.bin", ".env", "tls.pem"):
        assert never_packed not in coverage

    # Files left out on purpose are declared in the manifest.
    manifest = json.loads((project.root / "repomix.packs.json").read_text())
    manifest["coverage_ignore"] = ["src/c"]
    project.write("repomix.packs.json", json.dumps(manifest))
    project.run()
    assert "in no pack" not in project.status()


# ---------------------------------------------------------------------------
# A5 / A11: hook runs never wait; queued re-checks; mkdir lock without flock
# ---------------------------------------------------------------------------
def test_no_wait_run_returns_at_once_when_a_build_holds_the_lock(project: Project) -> None:
    _standard(project)
    project.repomix.mkdir(exist_ok=True)
    with open(project.repomix / "update.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        start = time.monotonic()
        result = project.run("--no-wait", timeout=20)
        elapsed = time.monotonic() - start
    assert result.returncode == 0
    assert elapsed < 10
    assert "will re-check when it finishes" in result.stdout
    assert (project.repomix / "update.pending").exists()
    assert project.builds() == []


def test_queued_recheck_rebuilds_changes_made_during_a_build(project: Project) -> None:
    _standard(project)
    project.run()
    project.write("src/app/a.txt", "alpha 2\n")
    slow_env = {**project.env, "FAKE_REPOMIX_SLEEP": "1.5"}
    builds_before = len(project.builds())
    first = subprocess.Popen(
        ["sh", str(project.root / "scripts/update-repomix-index.sh")],
        cwd=project.root, env=slow_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    deadline = time.monotonic() + 20
    while len(project.builds()) == builds_before and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(project.builds()) > builds_before, "the first build never started"
    # A commit lands while the slow build runs: its hook must not wait.
    project.write("src/app/c.txt", "gamma\n")
    hook_run = project.run("--no-wait", env=slow_env, timeout=20)
    assert "will re-check" in hook_run.stdout
    first.communicate(timeout=60)

    assert "RERUN: changes were queued during the build" in project.log()
    assert not (project.repomix / "update.pending").exists()
    assert "src/app/c.txt" in _packed_paths(project, "app")


@pytest.mark.skipif(not shutil.which("timeout"), reason="needs coreutils timeout")
def test_hung_repomix_is_stopped_by_the_build_timeout(project: Project) -> None:
    _standard(project)
    script = project.root / "scripts" / "update-repomix-index.sh"
    text = script.read_text(encoding="utf-8")
    assert "\nBUILD_TIMEOUT=900 " in text
    script.write_text(text.replace("\nBUILD_TIMEOUT=900 ", "\nBUILD_TIMEOUT=1   ", 1), encoding="utf-8")

    start = time.monotonic()
    result = project.run(env={**project.env, "FAKE_REPOMIX_SLEEP": "30"}, timeout=60)
    assert time.monotonic() - start < 20
    assert result.returncode == 0
    assert "FAIL(catalog): repomix exit 124" in project.log()
    assert project.row("app")[3] == "FAILED (no output)"


def _path_without_flock(tmp_path: Path, fakebin: Path) -> str:
    nobin = tmp_path / "bin-no-flock"
    nobin.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool, path="/usr/bin:/bin")
        if found:
            (nobin / tool).symlink_to(found)
    return f"{fakebin}:{nobin}"


def test_mkdir_lock_is_used_where_flock_is_missing(project: Project, tmp_path: Path) -> None:
    _standard(project)
    env = {**project.env, "PATH": _path_without_flock(tmp_path, Path(project.env["FAKE_REPOMIX_BIN"]).parent)}
    lock_dir = project.repomix / "update.lock.d"
    lock_dir.mkdir(parents=True)
    (lock_dir / "pid").write_text(f"{os.getpid()}\n")  # a live owner

    busy = project.run("--no-wait", env=env, timeout=20)
    assert busy.returncode == 0
    assert "will re-check" in busy.stdout
    assert project.builds() == []

    dead = subprocess.Popen(["true"])
    dead.wait()
    (lock_dir / "pid").write_text(f"{dead.pid}\n")  # owner died: lock is taken over
    taken = project.run("--no-wait", env=env, timeout=30)
    assert taken.returncode == 0, taken.stdout + taken.stderr
    assert project.row("app")[3] == "rebuilt"
    assert not lock_dir.exists()


# ---------------------------------------------------------------------------
# A6: npx fallback pinned, version shown
# ---------------------------------------------------------------------------
def test_npx_fallback_runs_the_pinned_version(project: Project, tmp_path: Path) -> None:
    _standard(project)
    npxbin = tmp_path / "npxbin"
    npxbin.mkdir()
    _write_exe(npxbin / "npx", FAKE_NPX)
    for tool in ("node", "git"):
        (npxbin / tool).symlink_to(shutil.which(tool))
    env = {**project.env, "PATH": f"{npxbin}:/usr/bin:/bin", "FAKE_NPX_CALLS": str(tmp_path / "npx.txt")}
    if shutil.which("repomix", path=env["PATH"]):
        pytest.skip("a real repomix is on /usr/bin")

    project.run(env=env)
    calls = (tmp_path / "npx.txt").read_text().splitlines()
    assert calls and all(c.startswith("--yes repomix@1.14.0 ") for c in calls)
    assert "repomix 1.14.0 via npx" in project.status()

    manifest = json.loads((project.root / "repomix.packs.json").read_text())
    manifest["repomix_version"] = "1.13.2"
    project.write("repomix.packs.json", json.dumps(manifest))
    project.run("--force", env=env)
    assert (tmp_path / "npx.txt").read_text().splitlines()[-1].startswith("--yes repomix@1.13.2 -c ")


# ---------------------------------------------------------------------------
# A7: repomix's security report and secret-like strings reach log + STATUS
# ---------------------------------------------------------------------------
def test_security_findings_reach_the_log_and_status(project: Project) -> None:
    project.write("src/app/a.txt", "alpha\n")
    project.write("src/app/creds.txt", "SUSPICIOUS token\n")
    project.write("src/app/Keys.php", '<?php\n$k = "sk_live_' + "4eC39HqLyjWDarjtT1zdp7dc" + '";\n')
    project.set_manifest([{"name": "app", "include": ["src/app/**"], "watch": ["src/app"]}])
    project.commit("init")

    project.run()
    log = project.log()
    assert "SECURITY(app): repomix excluded 1 suspicious file(s):" in log
    assert "| src/app/creds.txt" in log
    status = project.status()
    assert "repomix's secret check excluded 1 suspicious file(s) from pack 'app'" in status
    assert "pack 'app' contains secret-like strings from: src/app/Keys.php" in status
    assert "sk_live_" not in status and "sk_live_" not in log  # never the value itself

    project.run()  # fresh run: the findings stay visible
    assert "src/app/Keys.php" in project.status()
    assert "excluded 1 suspicious" in project.status()


# ---------------------------------------------------------------------------
# A8: honest failure log, failed pack keeps its row
# ---------------------------------------------------------------------------
def test_failed_build_logs_the_real_exit_code_and_keeps_its_row(project: Project) -> None:
    _standard(project)
    project.run()
    cfg = project.root / ".repomix/configs/app.json"
    data = json.loads(cfg.read_text())
    data["fail"] = 3
    cfg.write_text(json.dumps(data))

    project.run()
    log = project.log()
    assert "FAIL(app): repomix exit 3" in log
    assert "boom from fake repomix" in log
    assert project.row("app")[3] == "FAILED (old copy)"
    assert "**FAILED: app.**" in project.status()

    before = len(project.builds())
    project.run()  # a failed pack is retried, never reported fresh
    assert len(project.builds()) == before + 1


def test_missing_config_is_a_failed_row(project: Project) -> None:
    _standard(project)
    (project.root / ".repomix/configs/app.json").unlink()
    project.run()
    assert project.row("app")[3].startswith("FAILED (no config")


def test_legacy_monolith_logs_the_real_exit_code(project: Project) -> None:
    project.write("src/a.txt", "a\n")
    project.write("repomix.config.json", json.dumps({"output": {"filePath": ".repomix/output.xml"}, "fail": 4}))
    project.commit("init")
    project.run()
    assert "FAIL(legacy): repomix exit 4" in project.log()


def test_invalid_manifest_is_reported_in_status(project: Project) -> None:
    project.write("repomix.packs.json", "{ not json")
    project.commit("init")
    result = project.run()
    assert result.returncode == 0
    assert "repomix.packs.json cannot be read" in project.status()


# ---------------------------------------------------------------------------
# A10: --background with a relative $0 from a subdirectory
# ---------------------------------------------------------------------------
def test_background_run_from_a_subdirectory(project: Project) -> None:
    _standard(project)
    sub = project.root / "sub"
    sub.mkdir()
    result = project.run("--background", cwd=sub, script="../scripts/update-repomix-index.sh")
    assert result.returncode == 0
    pid = int(result.stdout.rsplit("(pid ", 1)[1].split(")")[0])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:  # wait for the detached run to finish
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    assert "nohup" not in project.log()
    assert "DONE: built=2" in project.log()
    assert (project.repomix / "PACKS_STATUS.md").exists()


# ---------------------------------------------------------------------------
# A13: leftovers, log rotation, .gitignore
# ---------------------------------------------------------------------------
def test_leftover_pack_files_are_removed(project: Project) -> None:
    _standard(project)
    project.write(".repomix/cart-order.xml", "This file is a merged representation ... by Repomix.\n")
    project.write(".repomix/notes.xml", "<notes/>\n")
    project.write(".repomix/output.xml", "This file is a merged representation ... by Repomix.\n")

    check = project.run("--check")
    assert (project.repomix / "cart-order.xml").exists()  # --check changes nothing
    assert "`.repomix/cart-order.xml` is not in the manifest" in project.status()
    assert check.returncode == 1

    project.run()
    assert not (project.repomix / "cart-order.xml").exists()
    assert (project.repomix / "notes.xml").exists()  # not a repomix output: not ours
    assert (project.repomix / "output.xml").exists()  # monolith: the user decides
    assert "REMOVED: .repomix/cart-order.xml" in project.log()
    assert "old monolithic index" in project.status()


def test_non_canonical_output_spelling_keeps_the_built_pack(project: Project) -> None:
    """`.repomix//./app.xml` names the file repomix writes; the leftover cleanup
    compared raw strings and deleted the pack it had just built."""
    _standard(project)
    manifest = json.loads((project.root / "repomix.packs.json").read_text())
    manifest["packs"][1]["output"] = ".repomix//./app.xml"
    project.write("repomix.packs.json", json.dumps(manifest))
    project.commit("spelling")

    for _ in range(2):
        assert project.run().returncode == 0
        assert (project.repomix / "app.xml").exists()
    assert "REMOVED" not in project.log()
    assert "not in the manifest" not in project.status()


def test_config_writing_another_file_is_a_failed_row_not_a_rebuild(project: Project) -> None:
    """A8: with output.filePath != manifest "output", the old XML was reported
    `rebuilt` and the file repomix really wrote was deleted as a leftover."""
    _standard(project)
    project.run()
    config = project.root / ".repomix" / "configs" / "app.json"
    cfg = json.loads(config.read_text())
    cfg["output"]["filePath"] = ".repomix/app-new.xml"
    project.write(".repomix/configs/app.json", json.dumps(cfg))
    project.commit("mismatch")
    builds = len(project.builds())

    assert project.run().returncode == 0
    assert len(project.builds()) == builds  # not built
    assert project.row("app")[3] == "FAILED (config writes `.repomix/app-new.xml`; old copy)"
    assert ("`.repomix/configs/app.json` writes `.repomix/app-new.xml` but the manifest "
            "\"output\" is `.repomix/app.xml`") in project.status()
    assert not (project.repomix / "app-new.xml").exists()
    assert project.run("--check").returncode == 1


def test_non_git_project_gets_a_coverage_note_not_a_problem(project: Project, tmp_path: Path) -> None:
    """Outside git, "Coverage not checked" was a Problem: `--check` always
    exited 1 and PACKS_STATUS always showed a problem banner."""
    root = tmp_path / "plain"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / SCRIPT.name)
    plain = Project(root, {**project.env, "GIT_CEILING_DIRECTORIES": str(tmp_path)})
    plain.write("src/app/a.txt", "alpha\n")
    plain.set_manifest([{"name": "app", "include": ["src/app/**"], "watch": ["src/app"]}])

    assert plain.run().returncode == 0
    status = plain.status()
    assert "Coverage not checked: not a git work tree." in status
    assert "All packs fresh and under the ceiling.\n" in status
    assert "problem(s)" not in status and "## Problems" not in status
    assert plain.run("--check").returncode == 0


def test_update_log_is_rotated(project: Project) -> None:
    _standard(project)
    project.write(".repomix/update.log", "old line\n" * 120_000)  # ~1.1 MB
    project.run()
    assert (project.repomix / "update.log.1").read_text().startswith("old line")
    assert (project.repomix / "update.log").stat().st_size < 100_000


def _guide_gitignore_block() -> str:
    guide = (QUICK_START / "INIT_GUIDE.md").read_text(encoding="utf-8")
    start = guide.index("```gitignore\n") + len("```gitignore\n")
    return guide[start:guide.index("```", start)]


def test_guide_gitignore_block_covers_every_build_file(project: Project) -> None:
    _standard(project)
    project.write(".gitignore", _guide_gitignore_block())
    project.write(".repomix/backup-2026-09-24/repomix.packs.json", "{}")
    project.run()
    for rel in (".repomix/app.xml", ".repomix/packs.state", ".repomix/update.log",
                ".repomix/backup-2026-09-24/repomix.packs.json", ".repomix/coverage.txt"):
        assert subprocess.run(["git", "check-ignore", "-q", rel], cwd=project.root,
                              env=project.env).returncode == 0, rel
    assert subprocess.run(["git", "check-ignore", "-q", ".repomix/configs/app.json"],
                          cwd=project.root, env=project.env).returncode == 1
    assert ".gitignore" not in project.status()


def test_outdated_gitignore_is_reported(project: Project) -> None:
    project.write(".gitignore", ".repomix/*.xml\n.repomix/update.log\n.repomix/update.lock\n.repomix/PACKS_STATUS.md\n")
    _standard(project)
    project.run()
    assert "`.gitignore` does not cover the build files" in project.status()


# ---------------------------------------------------------------------------
# --check: nothing built, exit status tells whether PACKS_STATUS.md warns
# ---------------------------------------------------------------------------
def test_check_mode_builds_nothing(project: Project) -> None:
    _standard(project)
    project.run()
    assert project.run("--check").returncode == 0

    project.write("src/app/new.txt", "new\n")
    before = len(project.calls())
    result = project.run("--check")
    assert result.returncode == 1
    assert len(project.calls()) == before
    assert project.row("app")[3] == "STALE"
    assert "src/app/new.txt" not in _packed_paths(project, "app")
