# 04 — AI Review Queue

> Workflow for materials the Python pipeline could not turn into knowledge automatically.

---

## Queues

| Folder | When entries land here | Who handles them |
|--------|------------------------|------------------|
| `review/needs-classification/` | Pipeline could not determine type/destination | AI agent |
| `review/needs-ai-decision/` | Needs semantic analysis | AI agent in IDE |
| `review/needs-redaction/` | Sensitive data detected | AI agent + human |
| `review/excluded-sensitive/` | Cannot be used | Nobody (archive) |
| `review/needs-heal/` | Catch-up items after an upgrade (`HEAL_PLAN.md`) | `!heal` — see `18_HEAL.md` |

All of `review/` is excluded from the Repomix index.

---

## Review-package format

The Python pipeline writes a package for each item in `review/needs-ai-decision/`:

```markdown
# AI Review: q2-growth-strategy.pdf

## Source

- Original: assets/documents/2026-05-06__q2-growth-strategy.pdf
- Conversion: processed/markdown/2026-05-06__q2-growth-strategy.md
- Detected type: strategy / research / presentation
- Confidence: medium

## Why review is needed

The material contains strategic decisions, audience insights, and potentially reusable frameworks.

## Likely extraction targets

- knowledge/domain/
- knowledge/projects/
- knowledge/decisions/
- knowledge/playbooks/
- assets-index/documents.md

## Questions for the AI agent

- What durable knowledge should be extracted?
- What decisions, principles, or frameworks are present?
- What is temporary and should not become permanent knowledge?
- Are there contradictions with existing files in `knowledge/`?
- Is redaction required before indexing?
```

---

## Prompt for the AI agent when processing review

```markdown
You are working with a local non-code knowledge base.

First read:
- AGENTS.md
- KNOWLEDGE_STRUCTURE.md
- kb.config.yml
- The chosen file from review/needs-ai-decision/

Your task: turn the material into clean knowledge for the Repomix index.

Rules:
1. Extract durable knowledge: facts, principles, decisions, insights, frameworks, voice
2. Do not carry over raw noise, transient details, or sensitive data
3. Update relevant files in knowledge/ (do not create duplicates)
4. Add frontmatter: source, extracted_at, tags
5. Update assets-index/ when describing a binary asset
6. If redaction is needed → review/needs-redaction/ with explanation
7. If context is missing → knowledge/open-questions/
8. Report which files were updated and why

Forbidden:
- Indexing raw/ and review/ directly
- Copying long chat fragments
- Adding personal data of third parties
- Creating new folders in knowledge/ without checking with the user
```

---

## Processing workflow

```text
1. Open review/needs-ai-decision/ in the IDE
2. Pick a review package
3. Read the linked file from processed/
4. Extract knowledge → update knowledge/
5. Delete the processed package from review/
6. Run ./shell/reindex.sh
```

---

## The `!review` command

The user can issue `!review` in chat to ask the agent to drain the queue. Contract:

1. **Scan in this order** (highest signal first):
   - `review/needs-redaction/` — sensitive material; either redact and re-route, or archive in `excluded-sensitive/`
   - `review/needs-ai-decision/` — main work
   - `review/needs-classification/` — uncertain type
2. **For every item** the agent reports:
   - **Source file**: which review package (path)
   - **Decision**: `extract` / `redact` / `archive` / `defer-to-user`
   - **Targets**: which `knowledge/<category>/<slug>.md` files were created or updated
   - **Why**: 1-2 sentences of rationale
3. **Long-form-book guard**: if the review package contains the "⚠️ Likely long-form reference book" block (added by `kb_ingest.py` for ≥25k-word PDF/EPUB/DOCX), the agent **must**:
   - NOT copy prose into `knowledge/voice/`
   - Write a takeaways note in `knowledge/principles/<book-slug>-takeaways.md` (5–15 bullets, in the user's words)
   - Update `knowledge/principles/<role>-bookshelf.md` (create if missing)
   - Reference the asset path via `source:` frontmatter
4. **Defer-to-user** when input is required — ask **one specific question per item**, batched at the end. Never block on the whole queue waiting for an answer.
5. **Delete the review package** once processed. Append a `review` entry to `log.md`.
6. **Reindex** at the end (or remind the user to).

If the queue is empty, respond with: *"Review queue is empty — nothing to process."*

If the queue is huge (>20 items), process the first 5–10 and ask the user whether to continue.

---
