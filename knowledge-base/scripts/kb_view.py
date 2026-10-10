#!/usr/bin/env python3
"""Local, read-only knowledge-graph viewer."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from collections import defaultdict
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import yaml

import kb_common as kbc


_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _page_id(path: Path, knowledge_dir: Path) -> str:
    return path.relative_to(knowledge_dir).with_suffix("").as_posix()


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None  # .nan / .inf are not valid JSON for the browser
    return value


# YAML anchors let a small page repeat one long value up to
# kbc.MAX_YAML_ALIASES times, so every frontmatter-derived field the viewer
# serves is capped: a page cannot inflate /api/graph or /api/page responses.
MAX_TAGS = 64
MAX_TAG_CHARS = 100
MAX_FIELD_CHARS = 200
METADATA_TEXT_BUDGET = 64 * 1024


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _bounded_json(value: Any, budget: list[int]) -> Any:
    """JSON-ready copy of ``value`` spending at most ``budget[0]`` characters;
    text past the budget is cut with ``…`` and further items are dropped."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if budget[0] <= 0:
                break
            name = _spend(str(key), budget)
            result[name] = _bounded_json(item, budget)
        return result
    if isinstance(value, (list, tuple, set)):
        items: list[Any] = []
        for item in value:
            if budget[0] <= 0:
                break
            items.append(_bounded_json(item, budget))
        return items
    value = _json_scalar(value)
    if isinstance(value, str):
        return _spend(value, budget)
    budget[0] -= 1
    return value


def _spend(text: str, budget: list[int]) -> str:
    if len(text) > budget[0]:
        text = f"{text[: max(budget[0], 0)]}…"
    budget[0] -= max(len(text), 1)
    return text


def _node_scalar(value: Any) -> Any:
    """A frontmatter scalar for a graph node; containers are not scalars."""
    value = _json_scalar(value)
    if isinstance(value, str):
        return _clip(value, MAX_FIELD_CHARS)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return None


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [
        _clip(str(item), MAX_TAG_CHARS)
        for item in list(value)[:MAX_TAGS]
        if not isinstance(item, (dict, list, tuple, set))
    ]


def _title(body: str, path: Path) -> str:
    match = _H1_RE.search(body)
    return match.group(1).strip() if match else path.stem


def _excerpt(body: str, limit: int = 240) -> str:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if _H1_RE.fullmatch(line):
            del lines[index]
            break
    text = " ".join(line.strip() for line in lines if line.strip())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _normalise_target(target: str) -> str:
    value = target.strip().replace("\\", "/")
    value = value.split("#", 1)[0].strip()
    if value.lower().startswith("knowledge/"):
        value = value[len("knowledge/") :]
    if value.lower().endswith(".md"):
        value = value[:-3]
    while value.startswith("./"):
        value = value[2:]
    return value.strip("/")


def _context_snippet(line: str, limit: int = 160) -> str:
    text = " ".join(line.split())
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _pagerank(
    order: list[str],
    outbound: dict[str, set[str]],
    *,
    damping: float = 0.85,
    iterations: int = 60,
) -> dict[str, float]:
    """Deterministic PageRank over resolved wikilinks (self-links ignored)."""
    count = len(order)
    if not count:
        return {}
    index = {page: position for position, page in enumerate(order)}
    # Positions instead of ids; pages and targets keep the same order, so the
    # float sums (and the rounded ranks) do not change.
    links = [
        [index[target] for target in sorted(outbound[page]) if target != page]
        for page in order
    ]
    linking = [(position, targets) for position, targets in enumerate(links) if targets]
    dangling_pages = [position for position, targets in enumerate(links) if not targets]
    rank = [1.0 / count] * count
    for _ in range(iterations):
        dangling = sum(rank[position] for position in dangling_pages)
        base = (1.0 - damping) / count + damping * dangling / count
        next_rank = [base] * count
        for position, targets in linking:
            share = damping * rank[position] / len(targets)
            for target in targets:
                next_rank[target] += share
        rank = next_rank
    return {page: round(rank[position], 6) for position, page in enumerate(order)}


def build_graph(kb_root: Path | str) -> dict[str, Any]:
    """Build a deterministic graph from ``knowledge/**/*.md`` in memory."""
    return build_viewer_state(kb_root)[0]


_TOKEN_RE = re.compile(r"[a-z0-9а-яё]+", re.IGNORECASE)
EXPLORATION_OVERLAP_MAX = 0.8
EXPLORATION_MAX_PAIRS = 2
# Candidate pairs scored at most per search: when nearly every pair is rejected
# (thousands of pages sharing most of their tags) the search stops there.
EXPLORATION_MAX_CHECKS = 50_000


def _token_set(text: str) -> set[str]:
    return {tok.casefold() for tok in _TOKEN_RE.findall(text or "") if len(tok) > 2}


_Features = tuple[frozenset[str], frozenset[str]]


def _overlap_features(node: dict[str, Any]) -> _Features:
    tags = frozenset(str(t).casefold() for t in (node.get("tags") or []) if t)
    tokens = frozenset(_token_set(str(node.get("label") or node.get("id") or "")))
    return tags, tokens


def _overlap(features_a: _Features, features_b: _Features) -> float:
    (tags_a, tokens_a), (tags_b, tokens_b) = features_a, features_b
    if tags_a or tags_b:
        return len(tags_a & tags_b) / len(tags_a | tags_b)
    union = tokens_a | tokens_b
    return (len(tokens_a & tokens_b) / len(union)) if union else 0.0


def overlap_score(node_a: dict[str, Any], node_b: dict[str, Any]) -> float:
    """Jaccard of tags; fall back to title tokens when both tag sets are empty."""
    return _overlap(_overlap_features(node_a), _overlap_features(node_b))


def undirected_components(graph: dict[str, Any]) -> list[list[str]]:
    """Connected components treating wikilinks as undirected."""
    nodes = [node["id"] for node in graph.get("nodes") or []]
    adj: dict[str, set[str]] = {page_id: set() for page_id in nodes}
    for node in graph.get("nodes") or []:
        page_id = node["id"]
        for other in list(node.get("outbound") or []) + list(node.get("inbound") or []):
            if other in adj:
                adj[page_id].add(other)
                adj[other].add(page_id)
    seen: set[str] = set()
    components: list[list[str]] = []
    for start in nodes:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        bucket: list[str] = []
        while stack:
            current = stack.pop()
            bucket.append(current)
            for nxt in sorted(adj[current]):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        components.append(sorted(bucket))
    return components


def _related_pages(ids: list[str], outbound: dict[str, list[str]]) -> list[int]:
    """Per page (index into ``ids``): bitset of the pages it reaches or that reach it.

    Tarjan's strongly connected components condense the link graph into a DAG,
    so reachability costs one pass over the links instead of a search per pair.
    """
    index = {page_id: i for i, page_id in enumerate(ids)}
    succ = [
        sorted({index[t] for t in outbound.get(page_id) or [] if t in index})
        for page_id in ids
    ]
    count = len(ids)
    order = [-1] * count
    low = [0] * count
    on_stack = [False] * count
    stack: list[int] = []
    comp = [-1] * count
    sccs: list[list[int]] = []  # emitted after every component they reach
    visited = 0
    for root in range(count):
        if order[root] != -1:
            continue
        order[root] = low[root] = visited
        visited += 1
        stack.append(root)
        on_stack[root] = True
        work = [(root, 0)]
        while work:
            page, edge = work[-1]
            if edge < len(succ[page]):
                work[-1] = (page, edge + 1)
                nxt = succ[page][edge]
                if order[nxt] == -1:
                    order[nxt] = low[nxt] = visited
                    visited += 1
                    stack.append(nxt)
                    on_stack[nxt] = True
                    work.append((nxt, 0))
                elif on_stack[nxt]:
                    low[page] = min(low[page], order[nxt])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[page])
            if low[page] == order[page]:
                members: list[int] = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    comp[member] = len(sccs)
                    members.append(member)
                    if member == page:
                        break
                sccs.append(members)

    own = [sum(1 << member for member in members) for members in sccs]
    down = list(own)
    for c, members in enumerate(sccs):
        for member in members:
            for nxt in succ[member]:
                if comp[nxt] != c:
                    down[c] |= down[comp[nxt]]
    up = list(own)
    for c in range(len(sccs) - 1, -1, -1):
        for member in sccs[c]:
            for nxt in succ[member]:
                if comp[nxt] != c:
                    up[comp[nxt]] |= up[c]
    return [down[comp[i]] | up[comp[i]] for i in range(count)]


def exploration_pairs(
    graph: dict[str, Any],
    *,
    max_pairs: int = EXPLORATION_MAX_PAIRS,
    overlap_max: float = EXPLORATION_OVERLAP_MAX,
    max_checks: int = EXPLORATION_MAX_CHECKS,
) -> list[dict[str, Any]]:
    """1–2 surprising pairs: different components, tag overlap < 0.8.

    Used by ``kb_reflect`` as the exploration slot. Empty list is honest —
    a fully linked graph has nothing to propose, and a search that scored
    `max_checks` candidate pairs without enough hits stops with what it has.
    """
    nodes = {node["id"]: node for node in graph.get("nodes") or []}
    if len(nodes) < 2 or max_pairs <= 0:
        return []
    features = {page_id: _overlap_features(node) for page_id, node in nodes.items()}

    def _rep(comp: list[str]) -> str:
        return max(
            comp,
            key=lambda page_id: (float(nodes[page_id].get("pagerank") or 0.0), page_id),
        )

    checks = 0

    def _pair(page_a: str, page_b: str, reason: str) -> dict[str, Any] | None:
        nonlocal checks
        if page_a == page_b:
            return None
        checks += 1
        score = _overlap(features[page_a], features[page_b])
        if score >= overlap_max:
            return None
        left, right = sorted((page_a, page_b))
        return {
            "a": left,
            "b": right,
            "overlap": round(score, 4),
            "reason": reason,
            "prompt": (
                f"What connects [[{left}]] and [[{right}]] "
                "that the graph does not show?"
            ),
        }

    pairs: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    def _add(item: dict[str, Any] | None) -> None:
        if item is None:
            return
        key = (item["a"], item["b"])
        if key in seen_keys:
            return
        seen_keys.add(key)
        pairs.append(item)

    components = [c for c in undirected_components(graph) if c]
    if len(components) >= 2:
        ranked = sorted(components, key=lambda comp: (-len(comp), comp[0]))
        reps = [_rep(comp) for comp in ranked]
        twins = _rejected_twins([features[rep] for rep in reps], overlap_max)
        everything = (1 << len(reps)) - 1
        for i, left_rep in enumerate(reps):
            later = everything & ~((1 << (i + 1)) - 1) & ~twins[i]
            while later:
                lowest = later & -later
                later ^= lowest
                right_rep = reps[lowest.bit_length() - 1]
                _add(_pair(left_rep, right_rep, "disconnected-components"))
                if len(pairs) >= max_pairs or checks >= max_checks:
                    return pairs

    outbound = {
        node["id"]: list(node.get("outbound") or []) for node in graph.get("nodes") or []
    }
    ids = sorted(nodes)
    related = _related_pages(ids, outbound)
    twins = _rejected_twins([features[page_id] for page_id in ids], overlap_max)
    everything = (1 << len(ids)) - 1
    for i, src in enumerate(ids):
        # Later pages (the old pairwise order) with no directed path either way.
        unrelated = everything & ~related[i] & ~((1 << (i + 1)) - 1) & ~twins[i]
        while unrelated:
            lowest = unrelated & -unrelated
            unrelated ^= lowest
            _add(_pair(src, ids[lowest.bit_length() - 1], "no-directed-path"))
            if len(pairs) >= max_pairs or checks >= max_checks:
                return pairs
    return pairs


def _rejected_twins(features: list[_Features], overlap_max: float) -> list[int]:
    """Per position: bitset of the positions whose features score exactly like
    its own, when such a pair always scores ``_overlap(f, f) >= overlap_max``.

    Tags decide the score whenever a page has any (title tokens count only
    when both tag sets are empty), so pages with the same non-empty tag set
    are twins. Skipping those pairs changes nothing in the output (they would
    be rejected), but a base where thousands of pages share one tag set no
    longer costs one overlap check per page pair.
    """
    keys = [
        (tags, frozenset()) if tags else (tags, tokens) for tags, tokens in features
    ]
    groups: dict[_Features, int] = {}
    for position, key in enumerate(keys):
        groups[key] = groups.get(key, 0) | (1 << position)
    rejected = {
        key: mask for key, mask in groups.items() if _overlap(key, key) >= overlap_max
    }
    return [rejected.get(key, 0) for key in keys]


class _Page(NamedTuple):
    """One parsed page plus everything derived from that file alone."""

    page_id: str
    meta: dict[str, Any]
    body: str
    fields: dict[str, Any]  # node fields read from the page itself
    links: tuple[tuple[str, str], ...]  # (normalised target, context)
    not_expected_linked: bool  # _archive/ or generated: never an orphan


PageCache = dict[str, tuple[tuple[int, int, int], _Page]]


def _load_viewer_config(root: Path) -> kbc.KbConfig:
    """kb.config.yml, or the code defaults when it does not parse (kb_lint
    reports a broken config; the viewer must still open)."""
    try:
        return kbc.load_config(root)
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return kbc.KbConfig(raw={}, root=root)


def _read_page(
    path: Path,
    info: os.stat_result,
    knowledge_dir: Path,
    cache: PageCache | None,
) -> _Page:
    """Parse one page; with ``cache``, an unchanged file is not parsed again
    and its title, excerpt and wikilinks are not extracted again."""
    signature = (info.st_mtime_ns, info.st_size, info.st_ino)
    key = str(path)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None and hit[0] == signature:
            return hit[1]
    meta, body = kbc.read_frontmatter_file(path)
    page_id = _page_id(path, knowledge_dir)
    lifecycle = meta.get("lifecycle", "evolving")
    page = _Page(
        page_id=page_id,
        meta=meta,
        body=body,
        fields={
            "label": _title(body, path),
            "tags": _tags(meta.get("tags")),
            "lifecycle": (
                "evolving"
                if isinstance(lifecycle, (dict, list, tuple, set))
                else _clip(str(lifecycle), MAX_FIELD_CHARS)
            ),
            "importance": _node_scalar(meta.get("importance")),
            "confidence": _node_scalar(meta.get("confidence")),
            "lastVerified": _node_scalar(meta.get("last_verified")),
            "excerpt": _excerpt(body),
        },
        links=tuple(
            (_normalise_target(target), _context_snippet(line))
            for target, line in kbc.extract_wikilinks_with_context(body)
        ),
        not_expected_linked=kbc.is_archived(page_id) or kbc.is_generated(meta),
    )
    if cache is not None:
        cache[key] = (signature, page)
    return page


def build_viewer_state(
    kb_root: Path | str,
    *,
    cache: PageCache | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the graph payload plus page bodies for full-text search.

    Only pages whose real path stays inside ``knowledge/`` are read (a symlink
    to ``.env`` is skipped). Pass the same ``cache`` dict to later calls to
    re-parse only the files whose mtime, size or inode changed.
    """
    root = Path(kb_root).resolve()
    knowledge_dir = root / "knowledge"
    pages = sorted(knowledge_dir.rglob("*.md")) if knowledge_dir.is_dir() else []
    cfg = _load_viewer_config(root)
    today = dt.date.today()

    records: dict[str, dict[str, Any]] = {}
    bodies: dict[str, str] = {}
    links: dict[str, tuple[tuple[str, str], ...]] = {}
    exact: dict[str, str] = {}
    by_slug: dict[str, list[str]] = defaultdict(list)
    not_expected_linked: set[str] = set()
    seen: set[str] = set()
    # Folder → its real path stays inside knowledge/ (checked once per folder;
    # only a symlinked page needs its own check).
    folder_inside: dict[str, bool] = {}

    for path in pages:
        key = str(path)
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                if kbc.resolve_under(knowledge_dir, path) is None:
                    continue
                info = path.stat()  # a dangling link raises here
            else:
                folder = os.path.dirname(key)
                if folder not in folder_inside:
                    folder_inside[folder] = (
                        kbc.resolve_under(knowledge_dir, Path(folder)) is not None
                    )
                if not folder_inside[folder]:
                    continue
            if not stat.S_ISREG(info.st_mode):
                continue
            page = _read_page(path, info, knowledge_dir, cache)
        except OSError:
            continue
        seen.add(key)
        page_id = page.page_id
        rel = f"knowledge/{page_id}.md"
        stale, stale_reason = kbc.stale_status(
            page.meta,
            rel,
            today=today,
            stale_days=cfg.lifecycle_stale_warning_days,
            by_folder=cfg.lifecycle_by_folder,
            default_lifecycle=cfg.lifecycle_default,
        )
        fields = page.fields
        records[page_id] = {
            "id": page_id,
            "label": fields["label"],
            "path": rel,
            "group": page_id.split("/", 1)[0] if "/" in page_id else "(root)",
            "tags": fields["tags"],
            "lifecycle": fields["lifecycle"],
            "importance": fields["importance"],
            "confidence": fields["confidence"],
            "lastVerified": fields["lastVerified"],
            "excerpt": fields["excerpt"],
            "stale": stale,
            "staleReason": stale_reason,
        }
        bodies[page_id] = page.body
        links[page_id] = page.links
        exact[page_id.casefold()] = page_id
        by_slug[page_id.rsplit("/", 1)[-1].casefold()].append(page_id)
        if page.not_expected_linked:
            not_expected_linked.add(page_id)

    if cache is not None:
        for key in set(cache) - seen:
            del cache[key]

    inbound: dict[str, set[str]] = {page_id: set() for page_id in records}
    outbound: dict[str, set[str]] = {page_id: set() for page_id in records}
    edges: list[dict[str, str]] = []
    broken: list[dict[str, str]] = []
    ambiguous: list[dict[str, Any]] = []

    for source in sorted(records):
        emitted = 0
        for target, context in links[source]:
            if "/" in target:
                resolved = exact.get(target.casefold())
                candidates = [resolved] if resolved else []
            else:
                candidates = sorted(by_slug.get(target.casefold(), []))

            if not candidates:
                broken.append(
                    {"source": source, "target": target, "context": context}
                )
                continue
            if len(candidates) > 1:
                ambiguous.append(
                    {
                        "source": source,
                        "target": target,
                        "candidates": candidates,
                        "context": context,
                    }
                )
                continue

            destination = candidates[0]
            edges.append(
                {
                    "id": f"{source}::{destination}::{emitted}",
                    "from": source,
                    "to": destination,
                    "target": target,
                    "context": context,
                }
            )
            emitted += 1
            outbound[source].add(destination)
            if destination != source:
                inbound[destination].add(source)

    order = sorted(records)
    pagerank = _pagerank(order, outbound)
    nodes: list[dict[str, Any]] = []
    orphans: list[str] = []
    for page_id in order:
        node = records[page_id]
        node_inbound = sorted(inbound[page_id])
        node_outbound = sorted(outbound[page_id])
        # Routing pages and routing-table.md are entry points, and _archive/
        # and generated pages are not expected to be linked; kb_lint applies
        # the same rule, so the two orphan counts stay comparable.
        entry_point = (
            node["group"] == "routing"
            or page_id.rsplit("/", 1)[-1] == "routing-table"
        )
        orphan = (
            not node_inbound
            and not entry_point
            and page_id not in not_expected_linked
        )
        if orphan:
            orphans.append(page_id)
        nodes.append(
            {
                **node,
                "inbound": node_inbound,
                "outbound": node_outbound,
                "inDegree": len(node_inbound),
                "outDegree": len(node_outbound),
                "orphan": orphan,
                "entryPoint": entry_point,
                "pagerank": pagerank[page_id],
            }
        )

    graph = {
        "nodes": nodes,
        "edges": edges,
        "diagnostics": {
            "broken": broken,
            "ambiguous": ambiguous,
            "orphans": orphans,
        },
        "stats": {
            "pages": len(nodes),
            "links": len(edges),
            "orphans": len(orphans),
            "broken": len(broken),
            "ambiguous": len(ambiguous),
        },
        # The rules behind the health counts, for the UI's explanations.
        "rules": {"staleWarningDays": cfg.lifecycle_stale_warning_days},
    }
    return graph, bodies


_FOLD_CHUNK = 1024


def _unfolded_index(text: str, folded_index: int) -> int:
    """Index in ``text`` of the character whose casefold covers ``folded_index``.

    ``casefold()`` works per character and may grow one (``ß`` → ``ss``), so a
    position found in the folded text can lie past the match in the original.
    Whole chunks are folded at C speed; only the chunk holding the position
    is walked character by character.
    """
    position = 0
    for start in range(0, len(text), _FOLD_CHUNK):
        chunk = text[start : start + _FOLD_CHUNK]
        grown = len(chunk.casefold())
        if position + grown <= folded_index:
            position += grown
            continue
        for offset, char in enumerate(chunk):
            position += len(char.casefold())
            if position > folded_index:
                return start + offset
    return len(text)


def _snippet(body: str, body_folded: str, needle: str) -> str:
    index = body_folded.find(needle)
    if index < 0:
        return ""
    match_end = index + len(needle)
    if len(body_folded) != len(body):
        index = _unfolded_index(body, index)
        match_end = _unfolded_index(body, match_end - 1) + 1
    start = max(0, index - 60)
    end = min(len(body), match_end + 90)
    snippet = " ".join(body[start:end].split())
    if start > 0:
        snippet = f"…{snippet}"
    if end < len(body):
        snippet = f"{snippet}…"
    return snippet


def search_pages(
    graph: dict[str, Any],
    bodies: dict[str, str],
    query: str,
    *,
    limit: int = 30,
    folded: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic full-text search over titles, ids, tags, and bodies.

    ``folded`` maps page ids to ``body.casefold()`` precomputed once per graph
    build; without it every body is folded on each query. Snippets are built
    only for the returned results.
    """
    needle = query.strip().casefold()
    if not needle:
        return []
    field_rank = {"title": 0, "tag": 1, "body": 2}
    hits: list[tuple[int, int, str, str, dict[str, Any]]] = []
    for node in graph["nodes"]:
        page_id = node["id"]
        if folded is not None:
            body_folded = folded[page_id]
        else:
            body_folded = bodies.get(page_id, "").casefold()
        occurrences = body_folded.count(needle)
        in_title = (
            needle in node["label"].casefold() or needle in page_id.casefold()
        )
        in_tags = any(needle in tag.casefold() for tag in node["tags"])
        if not (in_title or in_tags or occurrences):
            continue
        field = "title" if in_title else "tag" if in_tags else "body"
        matches = occurrences + (1 if in_title or in_tags else 0)
        hits.append((field_rank[field], -matches, page_id, field, node))
    hits.sort(key=lambda hit: hit[:3])

    results: list[dict[str, Any]] = []
    for _, negative_matches, page_id, field, node in hits[:limit]:
        body = bodies.get(page_id, "")
        body_folded = folded[page_id] if folded is not None else body.casefold()
        results.append(
            {
                "id": page_id,
                "label": node["label"],
                "path": node["path"],
                "group": node["group"],
                "field": field,
                "matches": -negative_matches,
                "snippet": _snippet(body, body_folded, needle),
            }
        )
    return results


def _safe_page_path(kb_root: Path | str, page_id: str) -> tuple[Path, Path]:
    root = Path(kb_root).resolve()
    knowledge_dir = (root / "knowledge").resolve()
    candidate_id = page_id.strip().replace("\\", "/")
    parts = candidate_id.split("/")
    if (
        not candidate_id
        or candidate_id.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
        or candidate_id.endswith(".md")
    ):
        raise ValueError("Invalid page id")
    candidate = (knowledge_dir / f"{candidate_id}.md").resolve()
    try:
        candidate.relative_to(knowledge_dir)
    except ValueError as exc:
        raise ValueError("Invalid page id") from exc
    return knowledge_dir, candidate


def load_page(kb_root: Path | str, page_id: str) -> dict[str, Any]:
    """Load one Markdown page, constrained to the knowledge directory."""
    knowledge_dir, path = _safe_page_path(kb_root, page_id)
    if not path.is_file():
        raise FileNotFoundError(page_id)
    metadata, body = kbc.read_frontmatter_file(path)
    canonical_id = _page_id(path, knowledge_dir)
    # Metadata text never exceeds the file itself (or 64 KiB): YAML aliases
    # cannot multiply one long value into a many-megabyte response.
    budget = [max(METADATA_TEXT_BUDGET, path.stat().st_size)]
    return {
        "id": canonical_id,
        "label": _title(body, path),
        "path": f"knowledge/{canonical_id}.md",
        "metadata": _bounded_json(metadata, budget),
        "markdown": body,
    }


def open_source_file(path: Path) -> None:
    """Open a validated Markdown file with the operating-system default app."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    subprocess.Popen(  # noqa: S603
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class ViewerServer(ThreadingHTTPServer):
    """Threaded localhost server carrying an in-memory graph snapshot."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[SimpleHTTPRequestHandler],
        *,
        kb_root: Path,
        asset_dir: Path,
        opener: Callable[[Path], None],
        shutdown_token: str | None,
    ) -> None:
        self.kb_root = kb_root.resolve()
        self.asset_dir = asset_dir.resolve()
        self.opener = opener
        self.shutdown_token = shutdown_token
        self._page_cache: PageCache = {}
        self._refresh_lock = threading.Lock()
        self._snapshot = self._build()
        super().__init__(server_address, request_handler)

    def _build(self) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
        graph, bodies = build_viewer_state(self.kb_root, cache=self._page_cache)
        folded = {page_id: body.casefold() for page_id, body in bodies.items()}
        return graph, bodies, folded

    @property
    def graph(self) -> dict[str, Any]:
        return self._snapshot[0]

    @property
    def bodies(self) -> dict[str, str]:
        return self._snapshot[1]

    def search(self, query: str) -> list[dict[str, Any]]:
        graph, bodies, folded = self._snapshot
        return search_pages(graph, bodies, query, folded=folded)

    def refresh(self) -> dict[str, Any]:
        # One rebuild at a time; unchanged pages come from the parse cache.
        with self._refresh_lock:
            self._snapshot = self._build()
            return self._snapshot[0]


def _host_allowed(host: str | None, port: int) -> bool:
    """True for ``localhost`` or an IP literal carrying the server's port.

    A DNS-rebinding page talks to the viewer under its own domain name, so
    every other name is refused; an IP literal cannot be rebound.
    """
    if not host or "@" in host:
        return False
    try:
        parsed = urlsplit(f"//{host}")
        hostname, host_port = parsed.hostname, parsed.port
    except ValueError:
        return False
    if not hostname or (host_port if host_port is not None else 80) != port:
        return False
    if hostname == "localhost":
        return True
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


class ViewerRequestHandler(SimpleHTTPRequestHandler):
    """Serve the static viewer and its deliberately small read-only API."""

    server: ViewerServer

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _refuse_foreign(self, *, check_origin: bool = False) -> bool:
        """Answer 403 and return True for a request from another site."""
        host = self.headers.get("Host")
        if not _host_allowed(host, self.server.server_address[1]):
            self._send_json({"error": "Forbidden host"}, HTTPStatus.FORBIDDEN)
            return True
        origin = self.headers.get("Origin")
        # Browsers send Origin with every POST; command-line clients may not.
        if check_origin and origin is not None and (
            origin.casefold() != f"http://{host}".casefold()
        ):
            self._send_json({"error": "Forbidden origin"}, HTTPStatus.FORBIDDEN)
            return True
        return False

    def _refuse_without_viewer_header(self) -> bool:
        """A custom header forces a CORS preflight, which this server refuses."""
        if self.headers.get("X-KB-Viewer") == "1":
            return False
        self._send_json(
            {"error": "Viewer action header required"}, HTTPStatus.FORBIDDEN
        )
        return True

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'",
        )
        super().end_headers()

    def _send_json(
        self, payload: Any, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        if self._refuse_foreign():
            return
        super().do_HEAD()

    def do_GET(self) -> None:  # noqa: N802
        if self._refuse_foreign():
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/api/health":
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/graph":
            self._send_json(self.server.graph)
            return
        if parsed.path == "/api/search":
            queries = parse_qs(parsed.query).get("q", [])
            if len(queries) != 1 or not queries[0].strip():
                self._send_json(
                    {"error": "Missing search query"}, HTTPStatus.BAD_REQUEST
                )
                return
            query = queries[0][:200]
            self._send_json(
                {
                    "query": query,
                    "results": self.server.search(query),
                }
            )
            return
        if parsed.path == "/api/page":
            page_ids = parse_qs(parsed.query).get("id", [])
            if len(page_ids) != 1:
                self._send_json(
                    {"error": "Missing page id"}, HTTPStatus.BAD_REQUEST
                )
                return
            try:
                page = load_page(self.server.kb_root, page_ids[0])
            except ValueError:
                self._send_json(
                    {"error": "Invalid page id"}, HTTPStatus.BAD_REQUEST
                )
                return
            except FileNotFoundError:
                self._send_json({"error": "Page not found"}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(page)
            return
        if parsed.path.startswith("/api/"):
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        self.path = "/index.html" if parsed.path == "/" else parsed.path
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self._refuse_foreign(check_origin=True):
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/api/refresh":
            if self._refuse_without_viewer_header():
                return
            self._send_json(self.server.refresh())
            return
        if parsed.path == "/api/open":
            if self._refuse_without_viewer_header():
                return
            page_ids = parse_qs(parsed.query).get("id", [])
            if len(page_ids) != 1:
                self._send_json(
                    {"error": "Missing page id"}, HTTPStatus.BAD_REQUEST
                )
                return
            try:
                _knowledge_dir, path = _safe_page_path(
                    self.server.kb_root, page_ids[0]
                )
                if not path.is_file():
                    raise FileNotFoundError(page_ids[0])
                self.server.opener(path)
            except ValueError:
                self._send_json(
                    {"error": "Invalid page id"}, HTTPStatus.BAD_REQUEST
                )
                return
            except FileNotFoundError:
                self._send_json({"error": "Page not found"}, HTTPStatus.NOT_FOUND)
                return
            except OSError as exc:
                self._send_json(
                    {"error": f"Cannot open page: {exc}"},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/shutdown":
            supplied = self.headers.get("X-KB-Viewer-Token", "")
            expected = self.server.shutdown_token or ""
            if not expected or not secrets.compare_digest(supplied, expected):
                self._send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
                return
            self._send_json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)


def create_server(
    *,
    kb_root: Path | str,
    asset_dir: Path | str,
    host: str = "127.0.0.1",
    port: int = 0,
    opener: Callable[[Path], None] | None = None,
    shutdown_token: str | None = None,
) -> ViewerServer:
    """Create but do not start a viewer server."""
    root = Path(kb_root).resolve()
    assets = Path(asset_dir).resolve()
    handler = partial(ViewerRequestHandler, directory=str(assets))
    return ViewerServer(
        (host, port),
        handler,
        kb_root=root,
        asset_dir=assets,
        opener=opener or open_source_file,
        shutdown_token=shutdown_token,
    )


_STATE_DIR_NAME = "ai-knowledge-engine-viewer"


def _state_dir() -> Path:
    """Per-user folder for the background viewer's URL and shutdown token.

    ``$XDG_RUNTIME_DIR`` when set (already private to the user); otherwise a
    ``-<uid>`` folder in the temp dir, created 0700. On Windows the temp dir
    is per user already.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if os.name != "nt" and os.path.isabs(runtime) and os.path.isdir(runtime):
        return Path(runtime) / _STATE_DIR_NAME
    if hasattr(os, "getuid"):
        return Path(tempfile.gettempdir()) / f"{_STATE_DIR_NAME}-{os.getuid()}"
    return Path(tempfile.gettempdir()) / _STATE_DIR_NAME


def state_file_for_root(kb_root: Path | str) -> Path:
    """Return an ephemeral per-KB state path outside the project tree."""
    root = Path(kb_root).resolve()
    identity = str(root).casefold() if os.name == "nt" else str(root)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return _state_dir() / f"{digest}.json"


def _legacy_state_file(kb_root: Path) -> Path | None:
    """Where engines before 0.16 kept the state (a shared temp folder)."""
    current = state_file_for_root(kb_root)
    legacy = Path(tempfile.gettempdir()) / _STATE_DIR_NAME / current.name
    return None if legacy == current else legacy


def _is_private_dir(directory: Path) -> bool:
    if os.name == "nt":
        return directory.is_dir()
    try:
        info = directory.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.getuid()
        and not stat.S_IMODE(info.st_mode) & 0o077
    )


def _is_own_file(path: Path) -> bool:
    """A regular file of this user: nobody else can have written it."""
    if os.name == "nt":
        return path.is_file()
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()


def _ensure_private_dir(directory: Path) -> None:
    """Create ``directory`` as 0700, or tighten one this user already owns."""
    directory.mkdir(mode=0o700, exist_ok=True)
    if os.name == "nt":
        return
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError(f"{directory} is not a private directory of this user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        directory.chmod(0o700)


def _read_state(state_file: Path, *, legacy: bool = False) -> dict[str, Any] | None:
    trusted = _is_own_file(state_file) if legacy else _is_private_dir(state_file.parent)
    if not trusted:
        return None
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not all(payload.get(key) for key in ("url", "token", "pid", "kbRoot")):
        return None
    return payload


def _remove_state(state_file: Path, *, pid: int | None = None) -> None:
    if not _is_private_dir(state_file.parent):
        return
    if pid is not None:
        current = _read_state(state_file)
        if current and current.get("pid") != pid:
            return
    try:
        state_file.unlink(missing_ok=True)
    except OSError:
        pass


def _running_state(
    kb_root: Path, *, include_legacy: bool = False, patient: bool = True
) -> dict[str, Any] | None:
    """The state of the viewer serving `kb_root`, or None (a dead one's state is removed).

    A viewer that answers late is busy (a loaded machine), not gone: it is asked
    again with a longer timeout and, while its process lives, still counts as
    running. `patient=False` (waiting for an acknowledged shutdown) takes only
    a prompt answer.
    """
    candidates = [(state_file_for_root(kb_root), False)]
    legacy_file = _legacy_state_file(kb_root)
    if include_legacy and legacy_file is not None:
        candidates.append((legacy_file, True))
    for state_file, legacy in candidates:
        state = _read_state(state_file, legacy=legacy)
        if state is not None:
            health = _health(state["url"], 0.6)
            if health == "slow" and patient:
                health = _health(state["url"], 2.0)
                if health == "slow" and _pid_alive(state["pid"]):
                    return state
            if health == "ok":
                return state
        if not legacy:
            _remove_state(state_file)
    return None


def _health(url: str, timeout: float) -> str:
    """``"ok"``, ``"slow"`` (no answer in time) or ``"gone"`` (refused, or not a viewer)."""
    try:
        with urlopen(f"{url}api/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return "ok" if response.status == HTTPStatus.OK and payload == {"ok": True} else "gone"
    except (OSError, URLError, ValueError) as exc:  # URLError and TimeoutError are OSErrors
        return "slow" if isinstance(getattr(exc, "reason", exc), TimeoutError) else "gone"


def _pid_alive(pid: Any) -> bool:
    """False only when no process `pid` exists (always True where that cannot be asked)."""
    if os.name == "nt" or not isinstance(pid, int) or pid <= 0:
        return True  # os.kill(pid, 0) would terminate the process on Windows
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _write_state(
    state_file: Path,
    *,
    url: str,
    token: str,
    kb_root: Path,
) -> None:
    """Write the state readable by this user only (it holds the shutdown token)."""
    _ensure_private_dir(state_file.parent)
    temporary = state_file.with_suffix(f".{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "url": url,
                    "token": token,
                    "pid": os.getpid(),
                    "kbRoot": str(kb_root),
                },
                ensure_ascii=False,
            )
        )
    temporary.replace(state_file)


def _background_command(
    *,
    kb_root: Path,
    asset_dir: Path,
    host: str,
    port: int,
    state_file: Path,
) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--kb-root",
        str(kb_root),
        "--asset-dir",
        str(asset_dir),
        "--host",
        host,
        "--port",
        str(port),
        "--no-browser",
        "--state-file",
        str(state_file),
    ]


def _start_background(
    *,
    kb_root: Path,
    asset_dir: Path,
    host: str,
    port: int,
    open_browser: bool,
) -> int:
    running = _running_state(kb_root)
    if running:
        print(f"Knowledge graph: {running['url']}")
        if open_browser:
            webbrowser.open(running["url"])
        return 0

    state_file = state_file_for_root(kb_root)
    try:
        _ensure_private_dir(state_file.parent)
    except OSError as exc:
        print(f"Cannot keep the viewer state private: {exc}", file=sys.stderr)
        return 2
    token = secrets.token_urlsafe(24)
    environment = os.environ.copy()
    environment["KB_VIEW_SHUTDOWN_TOKEN"] = token
    process_kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "env": environment,
    }
    if os.name == "nt":
        process_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    else:
        process_kwargs["start_new_session"] = True
    process = subprocess.Popen(  # noqa: S603
        _background_command(
            kb_root=kb_root,
            asset_dir=asset_dir,
            host=host,
            port=port,
            state_file=state_file,
        ),
        **process_kwargs,
    )

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        running = _running_state(kb_root)
        if running:
            print(f"Knowledge graph: {running['url']}")
            if open_browser:
                webbrowser.open(running["url"])
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.08)
    _remove_state(state_file)
    print("Knowledge graph failed to start.", file=sys.stderr)
    return 2


def _print_status(kb_root: Path) -> int:
    running = _running_state(kb_root, include_legacy=True)
    if not running:
        print("Knowledge graph is not running.")
        return 1
    print(f"Knowledge graph: {running['url']}")
    return 0


def _stop_background(kb_root: Path) -> int:
    # A viewer started by an older engine is found (and stopped) too.
    running = _running_state(kb_root, include_legacy=True)
    if not running:
        print("Knowledge graph is not running.")
        return 1
    request = Request(
        f"{running['url']}api/shutdown",
        method="POST",
        headers={"X-KB-Viewer-Token": running["token"]},
    )
    try:
        with urlopen(request, timeout=2) as response:
            if response.status != HTTPStatus.OK:
                raise OSError(f"shutdown returned {response.status}")
    except (HTTPError, URLError, OSError) as exc:
        print(f"Cannot stop knowledge graph: {exc}", file=sys.stderr)
        return 2

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if _running_state(kb_root, include_legacy=True, patient=False) is None:
            print("Knowledge graph stopped.")
            return 0
        time.sleep(0.08)
    print("Knowledge graph did not stop in time.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open a local read-only graph of knowledge/**/*.md"
    )
    parser.add_argument(
        "--kb-root",
        "--root",
        dest="kb_root",
        type=Path,
        default=None,
        help="Knowledge-base root (default: discover from current directory); "
        "--root is accepted as an alias for consistency with the other scripts",
    )
    parser.add_argument(
        "--asset-dir",
        type=Path,
        default=Path(__file__).with_name("kb_viewer"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the server without opening the default browser",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--background",
        action="store_true",
        help="Start once in the background, or reopen the running viewer",
    )
    mode.add_argument(
        "--status",
        action="store_true",
        help="Print the running viewer URL",
    )
    mode.add_argument(
        "--stop",
        action="store_true",
        help="Stop the background viewer for this knowledge base",
    )
    parser.add_argument("--state-file", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    kb_root = (
        args.kb_root.resolve()
        if args.kb_root is not None
        else kbc.find_kb_root(Path.cwd())
    )
    asset_dir = args.asset_dir.resolve()
    if args.status:
        return _print_status(kb_root)
    if args.stop:
        return _stop_background(kb_root)
    if not (asset_dir / "index.html").is_file():
        print(f"Viewer assets not found: {asset_dir}", file=sys.stderr)
        return 2
    if args.background:
        return _start_background(
            kb_root=kb_root,
            asset_dir=asset_dir,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )

    shutdown_token = os.environ.get("KB_VIEW_SHUTDOWN_TOKEN")
    try:
        server = create_server(
            kb_root=kb_root,
            asset_dir=asset_dir,
            host=args.host,
            port=args.port,
            shutdown_token=shutdown_token,
        )
    except OSError as exc:
        print(f"Cannot start knowledge graph server: {exc}", file=sys.stderr)
        return 2

    bound_host, bound_port = server.server_address[:2]
    display_host = "127.0.0.1" if bound_host in ("0.0.0.0", "::") else bound_host
    url = f"http://{display_host}:{bound_port}/"
    if args.state_file is not None:
        if not shutdown_token:
            print("Background viewer token is missing.", file=sys.stderr)
            server.server_close()
            return 2
        try:
            _write_state(
                args.state_file.resolve(),
                url=url,
                token=shutdown_token,
                kb_root=kb_root,
            )
        except OSError as exc:
            print(f"Cannot write viewer state: {exc}", file=sys.stderr)
            server.server_close()
            return 2
    print(f"Knowledge graph: {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if args.state_file is not None:
            _remove_state(args.state_file.resolve(), pid=os.getpid())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
