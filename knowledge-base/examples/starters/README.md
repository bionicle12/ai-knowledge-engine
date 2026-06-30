# Role starter templates

Ready-to-fill Markdown files for the first upload after deploying a knowledge base.
They are **not** ingested automatically — copy them into the matching `raw/<sub>/unsorted/`
folder, fill in your content, then run `./shell/reindex.sh`.

## Usage

```bash
# After kb_populate for your role:
cp examples/starters/battle-rap-producer/*.md raw/work/unsorted/          # adjust per file
cp examples/starters/battle-rap-producer/vocal-stack-main-recipe.md raw/personal-context/unsorted/
# … see each file's frontmatter `suggested_destination`

./shell/reindex.sh
```

| Folder | Role slug |
|--------|-----------|
| `battle-rap-producer/` | `battle-rap-producer` |
| `viral-short-form-veo/` | `viral-short-form-veo` |

Each starter file has YAML frontmatter with `suggested_destination` and `knowledge_target`
so the ingest pipeline can route it correctly after you copy it.
