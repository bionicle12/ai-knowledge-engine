# 13 — Auto-run: automatic processing on changes

> The knowledge base should refresh **automatically** when new data arrives. Three mechanisms: file watcher (daemon), git hook, cron — plus a consolidation step inside every full reindex.
>
> **Reference implementations** (they ship with the base; this module describes what they do — read the scripts for the exact code): `scripts/kb_watch.py`, `scripts/kb_reindex.py`, `scripts/kb_reflect.py`, `scripts/kb_nlp_batch.py`, `shell/watcher.sh`, `shell/reindex.sh`, `shell/install-hooks.sh`, `shell/hooks/post-commit`.

---

## Why

Manual `./shell/reindex.sh` after every change is friction — and friction means the base goes stale. Automation removes that barrier.

---

## Mode 1: file watcher (recommended for active work)

### Dependencies

`watchdog` (in `requirements.txt`). Without it `kb_watch.py` falls back to polling every 2 seconds — slower, same behaviour.

### What `scripts/kb_watch.py` does

It watches the folders in `autorun.watch_dirs` (default `raw/*/unsorted/` and `knowledge/`). Entries under `raw/` are ingest inboxes; `raw/*/unsorted/` includes the catch-all `raw/unsorted/`. Any other entry is watched for `.md` edits.

| Event | Wait | Action |
|-------|------|--------|
| New file in an inbox (nested folders included) | the file stays unchanged for `debounce_raw_seconds` (5) | the ready files are ingested together — `kb_ingest.py` with up to 100 paths per call (`--no-nlp` when `auto_nlp: false`) — then one `kb_reindex.py --no-ingest` |
| `.md` page created, edited, moved or deleted under `knowledge/` | `debounce_knowledge_seconds` (2) of quiet | `kb_lint.py --quick` (`auto_lint_on_change`), then `kb_reindex.py --no-ingest` (`auto_reindex_on_change`) |
| Watcher start | — | files already waiting in the inboxes are queued like new ones |

- **Never handed to ingest:** names matching `ingest.ignore_globs` (`.DS_Store`, `~$*`, `*.part`, `*.tmp`, …).
- **Ignored as edits:** `knowledge/routing/` and `knowledge/routing-table.md`. `kb_reindex.py` regenerates them through `kb_route.py`, which rewrites a page only when its content changes (dates and access counters stay put otherwise) — so the watcher never reacts to its own reindex.
- `--no-reindex` — never run `kb_reindex.py`; `--verbose` — print every command.
- **One watcher per base:** it holds `.kb-state/locks/watch.lock`; a second watcher exits with status 1.
- `--root` may be relative (it is resolved first); a folder without `kb.config.yml` is refused (exit 2).
- `autorun.watch_enabled: false` — `kb_watch.py` prints a note and exits 0.
- **Stopping:** on SIGTERM (`./shell/watcher.sh --stop`, systemd) the watcher finishes the step it is running (an ingest or a reindex is not cut in half), then exits. Ctrl+C in a terminal reaches that step's process too and interrupts it.

### Running via `shell/watcher.sh`

```bash
./shell/watcher.sh                  # foreground (Ctrl+C to stop); options go to kb_watch.py
./shell/watcher.sh --verbose        # e.g. foreground with every command printed
./shell/watcher.sh --daemon         # background: pidfile .watcher.pid, log .watcher.log
./shell/watcher.sh --status         # is the background watcher running?
./shell/watcher.sh --stop           # stop it and wait until it has exited
```

- The interpreter comes from `shell/_kbpy.sh`: `$KB_PYTHON`, else `.venv/bin/python`, else `python3`.
- `--daemon` reports an error (and shows the log tail) when the watcher exits right away — for example with `watch_enabled: false` or when another watcher already runs.
- `--stop` sends SIGTERM and waits up to 30 seconds for the process to exit; it says "stopped" only when it is gone. It first checks that the PID in `.watcher.pid` still belongs to the watcher, so a stale pidfile (reboot, PID reuse) never kills another program.
- Double-click launchers: `watcher-start.command` (macOS, Linux) and `watcher-start.bat` (Windows) run the watcher in the foreground of their terminal window (Ctrl+C or closing the window stops it); `watcher-stop.command` runs `./shell/watcher.sh --stop` for a `--daemon` watcher.

### Systemd unit (Linux)

```ini
# ~/.config/systemd/user/kb-watch.service
[Unit]
Description=Knowledge Base File Watcher

[Service]
Type=simple
WorkingDirectory=/path/to/knowledge-base
ExecStart=/path/to/knowledge-base/.venv/bin/python scripts/kb_watch.py --root /path/to/knowledge-base
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now kb-watch
systemctl --user status kb-watch
```

Do not run the systemd unit and `./shell/watcher.sh --daemon` for the same base — the second watcher exits (status 1) and systemd restarts it forever.

---

## Mode 2: git hook

For bases under git control.

```bash
bash shell/install-hooks.sh   # once per clone: .git/hooks/ is not versioned
```

`install-hooks.sh` (plain POSIX sh, so `sh shell/install-hooks.sh` works too) installs `shell/hooks/post-commit` into the repository's hooks folder (`git rev-parse --git-path hooks`) and warns when `core.hooksPath` points elsewhere. Any existing `post-commit` that differs from the shipped one — a foreign hook, or an older or edited copy of ours — is moved to `post-commit.backup-<timestamp>` first, never deleted. A base in a subfolder of the work tree is recorded in `git config kb.root`. The hook starts `kb_reindex.py --hook` in the background and returns at once:

- **Finding the base:** the `kb.root` folder, else the top of the work tree (for example after `finalize.sh` flattened the project). No base there — the hook does nothing.
- **Hook mode is light:** index + `STATUS.md` only — no ingest, no reflection request. The watcher or a manual reindex does the rest.
- It takes the pipeline lock with a short timeout and exits quietly when another run holds it.
- Output goes to `.kb-state/hooks.log` (never to `/dev/null`: swallowed errors are how indexes silently rot); above 1 MB the log moves to `hooks.log.1`.
- The hook always exits 0 — it never blocks a commit.
- The installed copy is replaced by the next `install-hooks.sh` run. To combine it with your own post-commit commands, keep your own hook and call `sh <base>/shell/hooks/post-commit` from it instead of running the installer.

Hard-earned hook rules (each one is a real production failure), in case you write your own hook:

1. `post-commit` does not fire on `git pull`, merge or rebase. After those, run `./shell/reindex.sh` (or install the same hook as `post-merge` / `post-rewrite` yourself).
2. Git GUIs and IDEs run hooks with a bare `PATH` — delegate to `kb_reindex.py`, which *reports* a missing repomix instead of silently skipping.
3. A plain `... &` background job is killed by SIGHUP when the hook exits — use `nohup` and redirect output to a log file.
4. Hooks must never block git: always `exit 0`.
5. Keep hook sources in the repo (`shell/hooks/`) and document the one-command install after clone.

**Optional pre-commit check:** `python3 scripts/kb_lint.py --quick --only frontmatter` exits non-zero when a page has frontmatter errors; call it from `.git/hooks/pre-commit` to block such commits.

---

## Mode 3: cron (periodic tasks)

```bash
# crontab -e — a full reindex (with consolidation) every night at 03:00
0 3 * * * cd /path/to/knowledge-base && mkdir -p .kb-state && .venv/bin/python scripts/kb_reindex.py >> .kb-state/cron.log 2>&1
```

Never append tool output to `log.md`: it has a strict entry format and the scripts write their own entries.

> **Important:** the machine may be off — cron does not guarantee execution. That is why consolidation lives inside every full reindex (below), not in cron.

---

## Consolidation inside every reindex

Problem: cron tasks do not fire if the machine is off. Solution: every full `kb_reindex.py` run (`./shell/reindex.sh` is a thin wrapper around it) checks whether consolidation is due.

- **When:** `.last_consolidation` is older than `autorun.consolidation_interval_hours` (24), or missing. Not in `--quick`, `--index-only` or `--hook` runs.
- **What:** a full lint report (`lint-report.md`), `kb_nlp_batch.py --incremental`, then — when `autorun.consolidation_on_reindex` is true (the default) — the reflection check `kb_reflect.py --check-threshold`. On `THRESHOLD_MET` it runs `kb_reflect.py --generate`, which appends a `reflect-request` entry to `log.md`.
- **Then:** every reindex, consolidation or not, ends by rewriting `STATUS.md` (unless `status.enabled: false`) — the short hand-off the agent reads at session start ("reflection due … → !reflect").

Exact steps: `scripts/kb_reindex.py` and `kb-docs/05_INDEX.md`.

No script processes review queues or runs level-2 (AI) lint. The `mode_profiles.*.lint` settings (`level2_trigger`, `review_auto_process`) are agent policy — see `kb-docs/07_INTERACTION_LOOP.md` and `kb-docs/09_LINT.md`.

### Reflection trigger (`scripts/kb_reflect.py`)

The script only decides; the reflection itself is AI work (`!reflect`, ~15K tokens).

| Decision | Meaning |
|----------|---------|
| `THRESHOLD_MET` | A reflection is due: the change score since the last reflection reached the threshold |
| `STAGNANT` | It would be due, but the last two recorded reflections found 0 insights and no ingest arrived since — the scheduled reflection is suppressed; `!reflect` from the owner still runs |
| `SKIP` | Nothing to do |

- **Change score** since the last reflection: every `ingest` entry in `log.md` weighs its importance from the ingest metadata, or `default_ingest_importance` (1) when it has none; every changed `knowledge/` page weighs its `importance` (3 when unset). Generated pages (`generated_by`) and `_archive/` do not count.
- **Changed page:** `--record-result` stores a digest of every page in `.kb-state/reflection-pages.json`, and a page counts when its content differs from it. Access tracking (`last_accessed`, `access_count`) is not a change, and neither is a touch, checkout or restore that leaves the content as it was. Without that snapshot the evidence is weaker. When the last reflection is the local `.last_reflection` (a base from before 0.16, until its first `--record-result`), the file's mtime decides. When it is only a `reflect` entry in `log.md` (a fresh clone, or a reflection recorded on another machine), mtimes say nothing — a clone resets them all — so a page counts only when its `extracted_at`, `last_verified` or `valid_from` date is on or after the day of that reflection.
- **Threshold:** `mode_profiles.<mode>.reflection.importance_threshold` of the active mode (`knowledge_base.mode`). Weekly profiles (`trigger: "threshold+weekly"`): once `min_interval_days` have passed, the threshold drops to 1 — any change is due (0 with `require_changes: false`).
- **Last reflection:** the newer of `.last_reflection` and the last `reflect` entry in `log.md`, so a fresh clone without the gitignored marker does not recount its ingests. The entries after it are taken by position in `log.md`, so an ingest logged in the same second as `--record-result` still counts. A base that never reflected counts `min_interval_days` from its deployment: the older of `deployed_at` in `kb.config.yml` and the first `log.md` entry. Its first ingest is therefore not due on its own; `elapsed_days` in `--json` is then the days since deployment.
- **Who writes what:** only `--record-result N` writes state — `.last_reflection`, the page snapshot and a `reflect | insights: N` log entry (0 insights is a valid, expected result). `--generate` appends one `reflect-request` entry only on `THRESHOLD_MET`, and not again while one is pending; on `SKIP` or `STAGNANT` it logs nothing. Every other call is read-only: no flags, `--json`, `--check-threshold [--json]`, `--count-changes`. `--dry-run` is accepted but deprecated (nothing else writes anyway).
- `--check-threshold --json` prints `{decision, changes, threshold, mode, count, trigger, reason}`: `changes` is the weighted score compared with `threshold`, `count` the number of changed items, `trigger` `importance` or `weekly`.
- `--json` (no `--check-threshold`) adds the agent's brief: `max_insights_per_run` (a ceiling, not a quota), `meta_insight_allowed` (new ingests since the last reflection), `stagnation`, and `exploration` — at most two pairs of pages from disconnected graph components (overlap `< 0.8`) the agent may use as reflection questions. An empty list is valid. The pairs need the whole page graph, so only `--json` and a logged request build it.

### Smart reflection schedule (default mode)

```
Days without reflection:  1  2  3  4  5  6  7  8  9  10  ...
Were there changes?       -  -  -  -  -  -  -  -  ✓  -   ...
                                                    ↑
                                          Due! (≥7 days + changes)
```

- **< 7 days** (since the last reflection, or since deployment when there is none yet) → due only when the change score reaches `importance_threshold` (25)
- **≥ 7 days**, no changes → not due; days keep counting
- **≥ 7 days** and changes → due
- the agent finishes with `--record-result N`, which resets the count

### Guarantees

- Consolidation runs **at most once per `consolidation_interval_hours`** (`.last_consolidation` marker).
- It fires on **any** full reindex — manual, launcher (`reindex.command` / `reindex.bat`), watcher.
- If the machine was off for 3 days, the first full reindex catches up.
- Lint and the reflection check run **before** the index is rebuilt.

---

## Trigger table

| Event | Action | Source |
|-------|--------|--------|
| `!view` | Start or reopen the local read-only graph viewer | `python3 scripts/kb_view.py --background` |
| `!status` | Show what needs attention | `python3 scripts/kb_status.py --print` |
| New file in `raw/*/unsorted/` or `raw/unsorted/` | Ingest (+ NLP) → Reindex | `./shell/watcher.sh` |
| Edit in `knowledge/` | Quick lint + Reindex | `./shell/watcher.sh` |
| Git commit | Index + `STATUS.md` (`kb_reindex.py --hook`) | git hook |
| `!save` in AI session | Session capture (with enrichment) → Reindex | AI agent |
| `!reflect` | Reflection: insight generation (~15K tokens), then `kb_reflect.py --record-result N` | AI agent |
| `!audit` | Per-pack L2 review from `.repomix/audit/<pack>__request.md` | AI agent |
| `!profile-review` | Interview `knowledge/profile/` (3 questions at a time) | AI agent |
| `!quiz` | Five questions about what is already in the base; costliest mistakes first | AI agent |
| `!heal` | Catch-up after upgrade (`kb_heal.py --plan` / `--apply auto`) | AI agent |
| `!refactor` | Two-step instruction trim (`kb-docs/17_REFACTOR.md`) | AI agent |
| `kb_lint.py --fix` edited pages | Quick lint + Reindex (seen as `knowledge/` edits) | `./shell/watcher.sh` |
| AI did query-writeback | Write page → Reindex | AI agent |
| Nightly (optional) | Full reindex with consolidation | cron |
| Full reindex, consolidation due (> 24h) | Lint report + NLP batch + reflection check; `reflect-request` when `THRESHOLD_MET` | `kb_reindex.py` |

---

## Configuration in `kb.config.yml`

```yaml
autorun:
  watch_enabled: true               # false: kb_watch.py exits at once
  watch_dirs:                       # raw/… entries = ingest inboxes; others = .md edits
    - "raw/*/unsorted/"
    - "knowledge/"
  debounce_raw_seconds: 5           # a new file must stay unchanged this long
  debounce_knowledge_seconds: 2     # quiet time after knowledge/ edits
  auto_nlp: true                    # false: the watcher ingests with --no-nlp
  auto_lint_on_change: true         # quick lint on knowledge/ edits
  auto_reindex_on_change: true      # reindex on knowledge/ edits
  consolidation_interval_hours: 24  # min interval between consolidations
  consolidation_on_reindex: true    # consolidation requests a reflection when due
  # complexity_auto_threshold: deprecated — nlp.complexity_threshold is the only threshold

mode_profiles:
  default:
    reflection:
      trigger: "threshold+weekly"
      importance_threshold: 25
      min_interval_days: 7
      require_changes: true
      max_insights_per_run: 3
      # default_ingest_importance: 1  # weight of an ingest without importance
```

Every key has a code default: an older `kb.config.yml` without them keeps working.

---

## Integration

- **03_PIPELINE:** the watcher runs ingest for new inbox files, in batches
- **05_INDEX:** the watcher and the git hook run `kb_reindex.py`; every reindex ends with `STATUS.md`
- **07_INTERACTION_LOOP:** `kb_reflect.py` decides when a reflection is due; `!reflect` ends with `--record-result N`
- **09_LINT:** watcher → quick lint; consolidation → full lint report
- **10_LOG:** scripts append their own entries (`ingest`, `reflect-request`, `reflect`, …) to `log.md`
- **12_NLP:** the watcher runs NLP on ingest (`auto_nlp`); consolidation runs `kb_nlp_batch.py --incremental`
