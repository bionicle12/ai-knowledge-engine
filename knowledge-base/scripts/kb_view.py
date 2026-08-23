#!/usr/bin/env python3
"""Local, read-only knowledge-graph viewer."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
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
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import kb_common as kbc


_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _page_id(path: Path, knowledge_dir: Path) -> str:
    return path.relative_to(knowledge_dir).with_suffix("").as_posix()


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    return _json_scalar(value)


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return []


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
    links = {
        page: sorted(target for target in outbound[page] if target != page)
        for page in order
    }
    rank = {page: 1.0 / count for page in order}
    for _ in range(iterations):
        dangling = sum(rank[page] for page in order if not links[page])
        base = (1.0 - damping) / count + damping * dangling / count
        next_rank = dict.fromkeys(order, base)
        for page in order:
            targets = links[page]
            if not targets:
                continue
            share = damping * rank[page] / len(targets)
            for target in targets:
                next_rank[target] += share
        rank = next_rank
    return {page: round(value, 6) for page, value in rank.items()}


def build_graph(kb_root: Path | str) -> dict[str, Any]:
    """Build a deterministic graph from ``knowledge/**/*.md`` in memory."""
    return build_viewer_state(kb_root)[0]


_TOKEN_RE = re.compile(r"[a-z0-9а-яё]+", re.IGNORECASE)
EXPLORATION_OVERLAP_MAX = 0.8
EXPLORATION_MAX_PAIRS = 2


def _token_set(text: str) -> set[str]:
    return {tok.casefold() for tok in _TOKEN_RE.findall(text or "") if len(tok) > 2}


def overlap_score(node_a: dict[str, Any], node_b: dict[str, Any]) -> float:
    """Jaccard of tags; fall back to title tokens when both tag sets are empty."""
    tags_a = {str(t).casefold() for t in (node_a.get("tags") or []) if t}
    tags_b = {str(t).casefold() for t in (node_b.get("tags") or []) if t}
    if tags_a or tags_b:
        union = tags_a | tags_b
        return (len(tags_a & tags_b) / len(union)) if union else 0.0
    tokens_a = _token_set(str(node_a.get("label") or node_a.get("id") or ""))
    tokens_b = _token_set(str(node_b.get("label") or node_b.get("id") or ""))
    union = tokens_a | tokens_b
    return (len(tokens_a & tokens_b) / len(union)) if union else 0.0


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


def _has_directed_path(
    outbound: dict[str, list[str]], start: str, goal: str
) -> bool:
    if start == goal:
        return True
    seen = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        for nxt in outbound.get(current) or []:
            if nxt == goal:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def exploration_pairs(
    graph: dict[str, Any],
    *,
    max_pairs: int = EXPLORATION_MAX_PAIRS,
    overlap_max: float = EXPLORATION_OVERLAP_MAX,
) -> list[dict[str, Any]]:
    """1–2 surprising pairs: different components, tag overlap < 0.8.

    Used by ``kb_reflect`` as the exploration slot. Empty list is honest —
    a fully linked graph has nothing to propose.
    """
    nodes = {node["id"]: node for node in graph.get("nodes") or []}
    if len(nodes) < 2 or max_pairs <= 0:
        return []

    def _rep(comp: list[str]) -> str:
        return max(
            comp,
            key=lambda page_id: (float(nodes[page_id].get("pagerank") or 0.0), page_id),
        )

    def _pair(page_a: str, page_b: str, reason: str) -> dict[str, Any] | None:
        if page_a == page_b:
            return None
        score = overlap_score(nodes[page_a], nodes[page_b])
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
        for i, left_comp in enumerate(ranked):
            for right_comp in ranked[i + 1 :]:
                _add(_pair(_rep(left_comp), _rep(right_comp), "disconnected-components"))
                if len(pairs) >= max_pairs:
                    return pairs

    outbound = {
        node["id"]: list(node.get("outbound") or []) for node in graph.get("nodes") or []
    }
    ids = sorted(nodes)
    for i, src in enumerate(ids):
        for dst in ids[i + 1 :]:
            if _has_directed_path(outbound, src, dst) or _has_directed_path(
                outbound, dst, src
            ):
                continue
            _add(_pair(src, dst, "no-directed-path"))
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def build_viewer_state(
    kb_root: Path | str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the graph payload plus page bodies for full-text search."""
    root = Path(kb_root).resolve()
    knowledge_dir = root / "knowledge"
    pages = sorted(knowledge_dir.rglob("*.md")) if knowledge_dir.is_dir() else []

    records: dict[str, dict[str, Any]] = {}
    bodies: dict[str, str] = {}
    exact: dict[str, str] = {}
    by_slug: dict[str, list[str]] = defaultdict(list)

    for path in pages:
        page_id = _page_id(path, knowledge_dir)
        meta, body = kbc.read_frontmatter_file(path)
        group = page_id.split("/", 1)[0] if "/" in page_id else "(root)"
        records[page_id] = {
            "id": page_id,
            "label": _title(body, path),
            "path": f"knowledge/{page_id}.md",
            "group": group,
            "tags": _tags(meta.get("tags")),
            "lifecycle": str(meta.get("lifecycle", "evolving")),
            "importance": _json_scalar(meta.get("importance")),
            "confidence": _json_scalar(meta.get("confidence")),
            "lastVerified": _json_scalar(meta.get("last_verified")),
            "excerpt": _excerpt(body),
        }
        bodies[page_id] = body
        exact[page_id.casefold()] = page_id
        by_slug[path.stem.casefold()].append(page_id)

    inbound: dict[str, set[str]] = {page_id: set() for page_id in records}
    outbound: dict[str, set[str]] = {page_id: set() for page_id in records}
    edges: list[dict[str, str]] = []
    broken: list[dict[str, str]] = []
    ambiguous: list[dict[str, Any]] = []

    for source in sorted(records):
        emitted = 0
        for raw_target, line in kbc.extract_wikilinks_with_context(bodies[source]):
            target = _normalise_target(raw_target)
            context = _context_snippet(line)
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
        # Routing pages and routing-table.md are entry points; kb_lint applies
        # the same rule, so the two orphan counts stay comparable.
        entry_point = node["group"] == "routing" or page_id == "routing-table"
        orphan = not node_inbound and not entry_point
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
    }
    return graph, bodies


def search_pages(
    graph: dict[str, Any],
    bodies: dict[str, str],
    query: str,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Deterministic full-text search over titles, ids, tags, and bodies."""
    needle = query.strip().casefold()
    if not needle:
        return []
    results: list[dict[str, Any]] = []
    for node in graph["nodes"]:
        page_id = node["id"]
        body = bodies.get(page_id, "")
        body_folded = body.casefold()
        occurrences = body_folded.count(needle)
        in_title = (
            needle in node["label"].casefold() or needle in page_id.casefold()
        )
        in_tags = any(needle in tag.casefold() for tag in node["tags"])
        if not (in_title or in_tags or occurrences):
            continue
        field = "title" if in_title else "tag" if in_tags else "body"
        snippet = ""
        index = body_folded.find(needle)
        if index >= 0:
            start = max(0, index - 60)
            end = min(len(body), index + len(needle) + 90)
            snippet = " ".join(body[start:end].split())
            if start > 0:
                snippet = f"…{snippet}"
            if end < len(body):
                snippet = f"{snippet}…"
        results.append(
            {
                "id": page_id,
                "label": node["label"],
                "path": node["path"],
                "group": node["group"],
                "field": field,
                "matches": occurrences + (1 if in_title or in_tags else 0),
                "snippet": snippet,
            }
        )
    field_rank = {"title": 0, "tag": 1, "body": 2}
    results.sort(
        key=lambda item: (
            field_rank[item["field"]],
            -item["matches"],
            item["id"],
        )
    )
    return results[:limit]


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
    return {
        "id": canonical_id,
        "label": _title(body, path),
        "path": f"knowledge/{canonical_id}.md",
        "metadata": _json_ready(metadata),
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
        self.graph, self.bodies = build_viewer_state(self.kb_root)
        super().__init__(server_address, request_handler)

    def refresh(self) -> dict[str, Any]:
        self.graph, self.bodies = build_viewer_state(self.kb_root)
        return self.graph


class ViewerRequestHandler(SimpleHTTPRequestHandler):
    """Serve the static viewer and its deliberately small read-only API."""

    server: ViewerServer

    def log_message(self, _format: str, *_args: Any) -> None:
        return

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
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
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
                    "results": search_pages(
                        self.server.graph, self.server.bodies, query
                    ),
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
        parsed = urlsplit(self.path)
        if parsed.path == "/api/refresh":
            self._send_json(self.server.refresh())
            return
        if parsed.path == "/api/open":
            if self.headers.get("X-KB-Viewer") != "1":
                self._send_json(
                    {"error": "Viewer action header required"},
                    HTTPStatus.FORBIDDEN,
                )
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


def state_file_for_root(kb_root: Path | str) -> Path:
    """Return an ephemeral per-KB state path outside the project tree."""
    root = Path(kb_root).resolve()
    identity = str(root).casefold() if os.name == "nt" else str(root)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return (
        Path(tempfile.gettempdir())
        / "ai-knowledge-engine-viewer"
        / f"{digest}.json"
    )


def _read_state(state_file: Path) -> dict[str, Any] | None:
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
    if pid is not None:
        current = _read_state(state_file)
        if current and current.get("pid") != pid:
            return
    try:
        state_file.unlink(missing_ok=True)
    except OSError:
        pass


def _running_state(kb_root: Path) -> dict[str, Any] | None:
    state_file = state_file_for_root(kb_root)
    state = _read_state(state_file)
    if state is None:
        _remove_state(state_file)
        return None
    try:
        with urlopen(f"{state['url']}api/health", timeout=0.6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if response.status == HTTPStatus.OK and payload == {"ok": True}:
            return state
    except (OSError, URLError, ValueError, TimeoutError):
        pass
    _remove_state(state_file)
    return None


def _write_state(
    state_file: Path,
    *,
    url: str,
    token: str,
    kb_root: Path,
) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_file.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "url": url,
                "token": token,
                "pid": os.getpid(),
                "kbRoot": str(kb_root),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
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
    running = _running_state(kb_root)
    if not running:
        print("Knowledge graph is not running.")
        return 1
    print(f"Knowledge graph: {running['url']}")
    return 0


def _stop_background(kb_root: Path) -> int:
    running = _running_state(kb_root)
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
        if _running_state(kb_root) is None:
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
        _write_state(
            args.state_file.resolve(),
            url=url,
            token=shutdown_token,
            kb_root=kb_root,
        )
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
