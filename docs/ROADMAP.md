# Roadmap

> Phased plan for AI Knowledge Engine. Status reflects the current `VERSION`
> (0.16.0). The latest released version is the source of truth; this file
> tracks intent. `kb.config.yml` keys marked `# not implemented yet (see
> docs/ROADMAP.md)` are listed under **Next**.

## Done

- **Core pipeline** — ingest (convert → assets → NLP → route), lint, log,
  provenance (source hashes), Repomix indexing.
- **Mode profiles** — `default` (Python-first, throttled) vs `super` (AI-first).
- **Autorun** — file watcher with polling fallback.
- **Upgrade path** — `kb_upgrade.py` syncs reference scripts into deployed bases.
- **Media processing (0.10.0)** — out-of-the-box transcription (STT) and OCR
  that need no system tools, archive unpacking, cross-platform reindex
  orchestrator, and `kb_doctor` media checks. See `15_MEDIA_PROCESSING.md`.
- **Graph viewer (0.11.0)** — `!view`: a local, offline graph of pages and
  wikilinks with base-health diagnostics.
- **Cross-base merge (0.12.0)** — `kb_export.py` / `kb_import.py` plus the
  `!merge` agent command: two deployments of one base exchange knowledge
  through bundles, with content-fingerprint dedup, fast-forward for untouched
  pages, and conflicts routed to `review/needs-merge/`. See `16_MERGE.md`.
- **Pack-based context index (0.13.0)** — semantic Repomix packs under a
  per-window token ceiling instead of one monolithic index. See `05_INDEX.md`.
- **Maintenance loop (0.15.0)** — instruction invariants and eval lite,
  `!refactor` (`17_REFACTOR.md`), catch-up `!heal` after upgrades
  (`18_HEAL.md`), Codex-first agent environment.
- **Closing the loop (0.16.0)** — `STATUS.md` hand-off from scripts to the
  agent, an extraction registry so processed material cannot silently skip
  `knowledge/`, runtime modules in the base's `kb-docs/`, pipeline locks,
  line-based `kb.config.yml` editing that keeps comments, one stale rule for
  lint and viewer. See `CHANGELOG.md` for the full list.
- **Russian instructions (0.16.0)** — all 22 documents in `i18n/ru/` now
  match the current EN instruction text. Translation metadata records the
  canonical source revision; see `i18n/TRANSLATION_STATUS.md` for drift checks.

## Next

- [ ] Surprise filter (`mode_profiles.*.surprise`): score how new a source is
      against the base (Python NLP overlap in `default`, AI in `super`). The
      keys are reserved; nothing reads them yet.
- [ ] Scheduled Level-2 lint (`mode_profiles.*.lint.level2_weekly_day`):
      L2 lint is agent work following `level2_trigger`; no scheduler reads
      the weekly day yet.
- [ ] Optional cloud STT backend wiring (off by default; `media.stt.allow_cloud`
      is reserved).
- [ ] PDF OCR fallback: when `pypdf` extracts little/no text, route scanned PDFs
      through `kb_ocr`.
- [ ] Speaker diarization for multi-speaker transcripts.
- [ ] NLP language detection: nlp-meta `language` is `language_policy.primary`
      today (`12_NLP_PREPROCESS.md`); detecting it per file needs a new
      optional dependency.
- [ ] Selective merge: `kb_export.py --only` picks top-level sections; let
      `!merge` pull a single `knowledge/<domain>` folder.
- [ ] Text-level merge of a page both bases edited. `kb_import.py` already
      decides by the common ancestor (`merge_source_fingerprint`) which side
      changed a page and merges the metadata three-way, but the ancestor is
      only a fingerprint, so a body changed on both sides goes to
      `review/needs-merge/`.
- [ ] Deploy context budget: the modules a deploy agent reads
      (`knowledge-base/README.md` + `NN_*.md`) grew from 188 KB (0.15) to
      274 KB in 0.16.0; 02/07/13/16 alone are 90 KB (0.15: 73 KB), 16_MERGE
      nearly doubled. `02_INIT.md` now separates full deployment reading
      (177 KB) from runtime-only modules, which are summarized at deploy
      time; `00_OVERVIEW.md` points to that split. Further trimming of
      02/07/16, especially 16's repeated examples, remains open.
- [ ] Transactional upgrade: an upgrade journal and `kb_upgrade.py
      --rollback-upgrade`. Today `--accept` / `--force` back up the file they
      replace (`.kb-state/upgrade-backups/`) and `kb_heal.py --rollback`
      undoes heal's auto fixes; the file sync itself has no undo. Likewise
      `finalize.sh` has `--resume` but no `--rollback`.
- [ ] `near-duplicate` lint check: reuse `sync.import.similarity_threshold`
      to flag a new `knowledge/` page that overlaps an existing one, so the
      "update before creating duplicates" rule is checked.

## Later / ideas

- [ ] Alternative indexers beyond Repomix (the legacy `indexer:` config key is
      not read; packs are Repomix-only).
- [ ] Move volatile page state (`last_accessed`, `access_count`) out of
      frontmatter into `.kb-state/`, so reading a page does not change it.
- [ ] One command registry that generates the command tables in `AGENTS.md`,
      `START_HERE.md`, `README.md` and `06_AGENTS_TEMPLATE.md`.
- [ ] A small TUI/inbox view over the `review/` queues.
- [ ] Viewer: an access token in the URL (other local users on a shared
      machine can reach `127.0.0.1:<port>`), a smaller `/api/graph` payload
      and a layout that settles on graphs with thousands of pages.
- [ ] Automatic regression assertions (a file such as
      `knowledge/_tests/assertions.yml` checked on every lint run); today the
      regression check is the manual `eval/QUESTIONS.md`.
- [ ] Confidence decay in lint: flag `confidence: high` pages whose
      `last_verified` is older than `lifecycle.confidence_decay_days`; today
      it is an agent rule (`11_PROVENANCE.md`) and no script reads the key.
