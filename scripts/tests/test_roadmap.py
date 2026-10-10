"""docs/ROADMAP.md stays honest about the config template and translations."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP = REPO_ROOT / "docs" / "ROADMAP.md"
TEMPLATE = REPO_ROOT / "knowledge-base" / "templates" / "kb.config.yml.template"

pytestmark = pytest.mark.skipif(
    not (ROADMAP.is_file() and TEMPLATE.is_file()), reason="engine repo checkout only"
)


def test_every_not_implemented_config_key_is_on_the_roadmap():
    # The template's "not implemented yet" markers send readers to the roadmap.
    keys = set()
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Za-z_][\w-]*):.*#.*not implemented yet", line)
        if m:
            keys.add(m.group(1))
    assert keys, "template has no 'not implemented yet' keys any more"
    roadmap = ROADMAP.read_text(encoding="utf-8")
    missing = sorted(k for k in keys if k not in roadmap)
    assert not missing, f"ROADMAP.md does not mention: {missing}"


def test_roadmap_claims_no_translation_only_when_none_exists():
    # MV26: the roadmap said 16_MERGE.md had no RU version while it had one.
    roadmap = ROADMAP.read_text(encoding="utf-8")
    for name, lang in re.findall(r"`([\w./-]+\.md)`\s+has no (\w+) version", roadmap):
        found = list((REPO_ROOT / "i18n" / lang.lower()).rglob(Path(name).name))
        assert not found, f"ROADMAP says {name} has no {lang} version: {found}"
