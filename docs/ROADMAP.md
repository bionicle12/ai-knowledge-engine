# Roadmap

> Phased plan for AI Knowledge Engine. Status reflects the current `VERSION`.
> The latest released version is the source of truth; this file tracks intent.

## Done

- **Core pipeline** — ingest (convert → assets → NLP → route), lint, log,
  provenance (source hashes), Repomix indexing.
- **Mode profiles** — `default` (Python-first, throttled) vs `super` (AI-first).
- **Autorun** — file watcher with polling fallback.
- **Upgrade path** — `kb_upgrade.py` syncs reference scripts into deployed bases.
- **Media processing (0.10.0)** — out-of-the-box transcription (STT) and OCR
  that need no system tools, archive unpacking, cross-platform reindex
  orchestrator, and `kb_doctor` media checks. See `15_MEDIA_PROCESSING.md`.
- **Cross-base merge** — `kb_export.py` / `kb_import.py` plus the `!merge`
  agent command: two deployments of one base exchange knowledge through
  bundles, with content-fingerprint dedup, fast-forward for untouched pages,
  and conflicts routed to `review/needs-merge/`. See `16_MERGE.md`.

## Next

- [ ] Implement (or formally delegate to the agent) the documented
      `importance` scoring and mode-aware surprise filter so metadata matches
      `03_PIPELINE.md`.
- [ ] PDF OCR fallback: when `pypdf` extracts little/no text, route scanned PDFs
      through `kb_ocr`.
- [ ] Optional cloud STT backend wiring (off by default; `media.stt.allow_cloud`).
- [ ] Speaker diarization for multi-speaker transcripts.
- [ ] Refresh `i18n/ru/` translations to clear the drift in
      `i18n/TRANSLATION_STATUS.md` — `16_MERGE.md` has no RU version at all.
- [ ] Selective merge: let `!merge` pull a single section (`--only
      knowledge/domain`) rather than the whole bundle.

## Later / ideas

- [ ] Alternative indexers beyond Repomix (the config already abstracts this).
- [ ] Incremental, content-addressed processed cache to skip unchanged inputs.
- [ ] A small TUI/inbox view over the `review/` queues.
