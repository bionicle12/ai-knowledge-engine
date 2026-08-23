# 16 — Cross-base merge (import & export)

> Contract for exchanging knowledge between **two deployments of the same base**
> — a studio laptop and a work laptop, a desktop and a travel machine.
>
> **Reference implementations:** `scripts/kb_export.py` (pack) and
> `scripts/kb_import.py` (merge). Wrappers: `shell/export.sh`, `shell/import.sh`,
> plus `export.command` / `import.command` (macOS) and `export.bat` /
> `import.bat` (Windows).

---

## The problem

The same base deployed twice diverges. One machine accumulates knowledge about
plugins and gear; the other accumulates analysis notes. Both edited
`knowledge/domain/tools.md`. Neither `rsync` nor a plain copy can help: the
first would overwrite one side's work, the second would leave two disconnected
piles of Markdown.

## Design goals

1. **Never lose knowledge.** No overwrite happens without a backup, and no
   ambiguous overwrite happens at all — it becomes a decision for the agent.
2. **Mechanics in Python, meaning in the agent.** The script does what is
   provably safe (dedup by content hash, additive copies, provenance stamps).
   Everything that needs judgement goes to `review/needs-merge/` and is settled
   by `!merge`.
3. **Idempotent.** Importing the same bundle twice changes nothing the second
   time.
4. **Converging, not accumulating.** Repeated syncs must not breed duplicates,
   so identical content is recognised regardless of filename, and pages that
   were imported and never touched locally fast-forward silently.

---

## The loop

```text
   machine A                         machine B
┌──────────────┐                  ┌──────────────┐
│  knowledge/  │                  │  knowledge/  │
└──────┬───────┘                  └──────▲───────┘
       │ kb_export.py                    │ kb_import.py
       ▼                                 │
 sync/outbox/bundle.zip ──── copy ──► sync/inbox/bundle.zip
                                         │
                                         ├─ safe cases  → applied automatically
                                         └─ ambiguous   → review/needs-merge/
                                                              │
                                                        !merge (agent)
                                                              │
                                          merged knowledge + contradiction audit
                                                              │
                                                          reindex
```

---

## Export

```bash
python3 scripts/kb_export.py                    # → sync/outbox/kb-bundle__<label>__<date>.zip
python3 scripts/kb_export.py --label studio-laptop
python3 scripts/kb_export.py --since 2026-06-01 # only knowledge touched since then
python3 scripts/kb_export.py --with-assets      # include binary originals
python3 scripts/kb_export.py --dry-run          # report contents, write nothing
```

### What travels

| Section | Path in bundle | Why |
|---------|----------------|-----|
| `knowledge` | `knowledge/**.md` | the knowledge itself |
| `assets-index` | `assets-index/**.md` | descriptions of binaries, cheap and useful |
| `interactions` | `interactions/**` | session history — append-only, never conflicts |
| `meta` | `meta/extracted-metadata/`, `meta/nlp-meta/` | provenance and NLP enrichment |
| `config` | `config/entities.yml` | role, language, tracked entities |
| `log` | `log.md` | the other base's operations chronology |
| `assets` | `assets/**` | **opt-in only** (`--with-assets`) |

### What never travels

`raw/`, `processed/` payloads, `review/` queues, `sync/` itself, `.repomix/`
output, and operational state (`.watcher.pid`, lint reports). Raw material stays
on the machine that produced it — it is the largest, the most private, and the
least useful to the other side.

> **Assets are opt-in on purpose.** For media-heavy roles the binaries dwarf the
> knowledge by three orders of magnitude. The default bundle carries the
> *descriptions* (`assets-index/`); when the importing base has no matching file,
> the entry is annotated with `- Note: original file not present in this base`,
> so the reference is honest instead of dangling.

### Manifest

Every bundle starts with `manifest.yml`: bundle format, source label, role,
language, export date, per-section counts, and for every file its size, SHA-256
and — for knowledge pages — a **content fingerprint** plus title, lifecycle and
importance. The fingerprint is what makes dedup work.

---

## Import

```bash
python3 scripts/kb_import.py                 # every *.zip in sync/inbox/
python3 scripts/kb_import.py bundle.zip
python3 scripts/kb_import.py --dry-run       # classify, write nothing
python3 scripts/kb_import.py --strategy prefer-incoming
```

### Content fingerprint

**The body is the knowledge; frontmatter is bookkeeping.** Two pages carry the
same knowledge when their normalized **bodies** match — line endings unified,
trailing whitespace stripped, trailing blank lines collapsed. Implemented in
`kb_common.content_fingerprint()`.

Frontmatter is deliberately outside the fingerprint. Reading a page on one
machine bumps `access_count`; tagging it there raises `importance`. None of that
is a reason to ask a human which version wins — the metadata is merged
non-destructively instead (tags unioned, counters raised to the maximum, dates
advanced to the newest, missing fields filled in, existing values never
replaced).

### Decision table

| Outcome | Condition | What happens |
|---------|-----------|--------------|
| `new` | no page at that path, no page with that slug, no page with that fingerprint | copied in, provenance stamped |
| `identical` | same path, same body, same metadata | skipped |
| `enriched` | same path and body, incoming metadata adds something | metadata merged — body untouched |
| `duplicate` | same body at a **different** path | skipped, reported (the page already exists under another name) |
| `fast-forward` | local body still matches the `merge_source_fingerprint` recorded at its last import — i.e. it was never edited here | body updated, local-only frontmatter fields preserved, backup kept |
| `conflict` | both bodies changed | **local file untouched**; incoming staged + diff written to `review/needs-merge/` |

A page classified `new` that overlaps ≥ `similarity_threshold` (default 0.85)
with an existing page is still added — knowledge is never withheld — but a
**merge candidate** package is written so the agent can consolidate the two.

### Provenance stamps

Imported pages get:

```yaml
merged_from: "studio-laptop"                  # sync.label of the source base
merge_bundle: "kb-bundle__studio-laptop__2026-07-31.zip"
imported_at: "2026-07-31T10:14:36+03:00"
merge_source_fingerprint: "sha256:1a2b3c…"    # fingerprint as imported
```

`merge_source_fingerprint` is the whole mechanism behind fast-forward: at the
next import, if the local fingerprint still equals it, nothing local was lost by
updating. If it differs, the user edited the page here too — that is a conflict.

These keys live in frontmatter, which is outside the fingerprint, so stamping
them never makes the page look changed to the other base.

### Non-knowledge sections

- **`assets-index/`** — merged block by block (`## <asset>`). Missing blocks are
  appended; existing ones are left alone.
- **`interactions/`, `processed/extracted-metadata/`, `processed/nlp-meta/`** —
  additive. Identical files are skipped; same-name-different-content files are
  kept side by side as `<name>__from-<label>.<ext>`.
- **`log.md`** — archived as `log-archive/imported__<label>__<date>.md`. The
  local log is never rewritten; the import itself is appended to it.
- **`config/entities.yml`** — **reported, never applied.** Adding an entity
  reshapes routing and folder layout, so it is the agent's call during `!merge`.

### Safety

- Every modified file is copied to `sync/backups/<timestamp>/<path>` first.
- Archive members with absolute paths or `..` are refused (zip-slip).
- `--dry-run` classifies everything and writes nothing.
- The bundle moves to `sync/applied/` only after a successful import.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | merged cleanly, nothing left to decide |
| `1` | merged, conflicts waiting in `review/needs-merge/` |
| `2` | error (no bundle, unreadable archive, unsupported format) |

---

## `!merge` — the agent's half

Run after every import. This is where the base actually gets *better* rather
than merely bigger.

**Cost:** ~5–40K tokens depending on the number of conflicts.

### Procedure

1. **Read the report.** Newest file in `sync/reports/`. It lists everything that
   was added, updated, skipped, and everything still undecided.

2. **Resolve every package in `review/needs-merge/`.**
   - *Conflicts:* read the local page and `_incoming/<path>` in full. Produce one
     merged page **at the local path** that keeps every claim true in either
     version and prefers the more specific formulation. Never drop a fact
     because the other side did not have it.
   - *Genuine contradictions* (the two sides assert incompatible things): keep
     the better-sourced claim, and record the other in
     `knowledge/open-questions/` with both sources and dates. Do not silently
     pick a winner.
   - *Merge candidates* (near-duplicates): if both pages describe the same
     thing, consolidate into the better-named one and move the other to
     `knowledge/_archive/` with `supersedes:`. If they differ, cross-link them
     with `[[wikilinks]]` instead.
   - After resolving, set `merge_source_fingerprint` on the merged page to the
     incoming page's fingerprint, refresh `last_verified`, keep the higher
     `importance`, union the `tags` — then delete the package and its
     `_incoming/` file.

3. **Audit for contradictions.** Over the merged pages *and their neighbours*
   (whatever they `[[link]]` to): does the imported knowledge contradict
   something the base already held? Two bases that diverged for months will
   disagree — surface it rather than let both statements sit in the index.

4. **Enrich.** This is the payoff of a merge:
   - cross-link imported pages into the existing graph with `[[wikilinks]]`
   - refresh `knowledge/routing/` (`python3 scripts/kb_route.py`)
   - if the import brought a coherent new area, consider whether it deserves an
     `insights/` page synthesizing both sides
   - report entities the other base tracks that this one does not, and ask the
     user whether to adopt them

5. **Finish.** Run `python3 scripts/kb_lint.py`, then reindex
   (`python3 scripts/kb_reindex.py`). Report to the user: what was added, what
   was merged, what contradicts what, and what you left in `open-questions/`.

### Rules for the agent

- **Never** resolve a conflict by deleting one side wholesale. If a fact exists
  only in the incoming version, it belongs in the merged page.
- **Never** apply `entities` changes from a bundle without asking.
- If a conflict cannot be settled without the user (both sides plausible, no
  source to arbitrate), ask **one** specific question about that page and move
  on to the next one — do not stall the whole merge.
- Long-form book rules from `03_PIPELINE.md` still apply: an imported page that
  is really the prose of a copyrighted work does not belong in `voice/`.

---

## Typical two-machine cycle

```bash
# on the studio laptop
./shell/export.sh --label studio-laptop
# copy sync/outbox/kb-bundle__studio-laptop__<date>.zip to the other machine's sync/inbox/

# on the work laptop
./shell/import.sh
# → "2 conflicts waiting in review/needs-merge/"
```

Then in the AI chat:

```
Use AGENTS.md as the primary instruction
!merge
```

Doing it in both directions leaves the two bases converged: each holds the union
of the knowledge, with contradictions surfaced instead of buried.

---

## Configuration (`kb.config.yml` → `sync`)

```yaml
sync:
  label: "studio-laptop"        # how this base identifies itself. MUST differ per machine
  export:
    sections: ["knowledge", "assets-index", "interactions", "meta", "config", "log"]
    with_assets: false
  import:
    strategy: "safe"            # safe | prefer-incoming | prefer-local
    similarity_threshold: 0.85
    backup: true
    move_applied: true
```

CLI flags override the config; the config overrides the built-in defaults.

| Strategy | Behaviour on a two-sided change |
|----------|--------------------------------|
| `safe` (default) | local untouched, conflict queued for `!merge` |
| `prefer-incoming` | incoming wins, backup kept in `sync/backups/` |
| `prefer-local` | incoming discarded, reported only |

`prefer-incoming` and `prefer-local` exist for bulk one-way syncs (a fresh base
pulling from an established one). For ordinary two-way work, use `safe` —
anything else silently picks a winner.

---

## Privacy

A bundle is knowledge, not raw material, but it is still **your** knowledge:
treat it as sensitive. Move it between machines the way you would move the base
itself. Nothing in the export path contacts the network, and `sync/` is excluded
from the index (`repomix.config.json`) and from git (`.gitignore`).

If the base is shared with someone else, export with `--only knowledge` and
review the result — `interactions/` contains session history, and
`meta/extracted-metadata/` contains original filenames.
