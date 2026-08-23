"""Tests for the local knowledge-graph viewer."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

import kb_view
import pytest


def test_kb_view_script_is_shipped() -> None:
    """Deleting the viewer entry point must break its deployment contract."""
    script = Path(__file__).resolve().parents[1] / "kb_view.py"
    assert script.is_file()


def _write_page(root: Path, rel: str, text: str) -> Path:
    path = root / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_build_graph_reads_metadata_titles_and_exact_wikilinks(tmp_path: Path) -> None:
    """Dropping metadata or path-qualified links must change the graph payload."""
    _write_page(
        tmp_path,
        "domain/source.md",
        "---\n"
        "tags: [retrieval, architecture]\n"
        "lifecycle: permanent\n"
        "importance: 8\n"
        "confidence: high\n"
        "last_verified: 2026-07-01\n"
        "---\n"
        "# Source Page\n\n"
        "A useful summary. See [[projects/target|the target]].\n",
    )
    _write_page(
        tmp_path,
        "projects/target.md",
        "# Target Page\n\nTarget body.\n",
    )

    graph = kb_view.build_graph(tmp_path)

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert sorted(nodes) == ["domain/source", "projects/target"]
    source_rank = nodes["domain/source"].pop("pagerank")
    target_rank = nodes["projects/target"].pop("pagerank")
    assert source_rank == pytest.approx(0.350877, rel=1e-3)
    assert target_rank == pytest.approx(0.649123, rel=1e-3)
    assert nodes["domain/source"] == {
        "id": "domain/source",
        "label": "Source Page",
        "path": "knowledge/domain/source.md",
        "group": "domain",
        "tags": ["retrieval", "architecture"],
        "lifecycle": "permanent",
        "importance": 8,
        "confidence": "high",
        "lastVerified": "2026-07-01",
        "excerpt": "A useful summary. See [[projects/target|the target]].",
        "inbound": [],
        "outbound": ["projects/target"],
        "inDegree": 0,
        "outDegree": 1,
        "orphan": True,
        "entryPoint": False,
    }
    assert nodes["projects/target"]["inbound"] == ["domain/source"]
    assert graph["edges"] == [
        {
            "id": "domain/source::projects/target::0",
            "from": "domain/source",
            "to": "projects/target",
            "target": "projects/target",
            "context": "A useful summary. See [[projects/target|the target]].",
        }
    ]
    assert graph["stats"] == {
        "pages": 2,
        "links": 1,
        "orphans": 1,
        "broken": 0,
        "ambiguous": 0,
    }


def test_build_graph_reports_broken_ambiguous_and_true_orphans(tmp_path: Path) -> None:
    """Guessing duplicate slugs or counting self-links as inbound must fail."""
    _write_page(
        tmp_path,
        "a/source.md",
        "# Source\n\n[[shared]] [[missing]] [[source]]\n",
    )
    _write_page(tmp_path, "a/shared.md", "# Shared A\n")
    _write_page(tmp_path, "b/shared.md", "# Shared B\n")
    _write_page(tmp_path, "b/linked.md", "# Linked\n\n[[a/source]]\n")

    graph = kb_view.build_graph(tmp_path)

    assert graph["edges"] == [
        {
            "id": "a/source::a/source::0",
            "from": "a/source",
            "to": "a/source",
            "target": "source",
            "context": "[[shared]] [[missing]] [[source]]",
        },
        {
            "id": "b/linked::a/source::0",
            "from": "b/linked",
            "to": "a/source",
            "target": "a/source",
            "context": "[[a/source]]",
        },
    ]
    assert graph["diagnostics"]["broken"] == [
        {
            "source": "a/source",
            "target": "missing",
            "context": "[[shared]] [[missing]] [[source]]",
        }
    ]
    assert graph["diagnostics"]["ambiguous"] == [
        {
            "source": "a/source",
            "target": "shared",
            "candidates": ["a/shared", "b/shared"],
            "context": "[[shared]] [[missing]] [[source]]",
        }
    ]
    assert graph["diagnostics"]["orphans"] == [
        "a/shared",
        "b/linked",
        "b/shared",
    ]
    assert graph["stats"] == {
        "pages": 4,
        "links": 2,
        "orphans": 3,
        "broken": 1,
        "ambiguous": 1,
    }


def test_build_graph_handles_missing_knowledge_directory(tmp_path: Path) -> None:
    """A bare directory must yield a usable empty graph, not crash."""
    graph = kb_view.build_graph(tmp_path)
    assert graph == {
        "nodes": [],
        "edges": [],
        "diagnostics": {"broken": [], "ambiguous": [], "orphans": []},
        "stats": {
            "pages": 0,
            "links": 0,
            "orphans": 0,
            "broken": 0,
            "ambiguous": 0,
        },
    }


def test_build_graph_flags_entry_points_and_ranks_hubs(tmp_path: Path) -> None:
    """Routing pages must be entry points and hubs must outrank leaves."""
    _write_page(
        tmp_path,
        "routing/routing-map.md",
        "# Routing Map\n\n[[a/hub]]\n",
    )
    _write_page(tmp_path, "a/hub.md", "# Hub\n\n[[a/leaf-one]] [[a/leaf-two]]\n")
    _write_page(tmp_path, "a/leaf-one.md", "# Leaf One\n\n[[a/hub]]\n")
    _write_page(tmp_path, "a/leaf-two.md", "# Leaf Two\n\n[[a/hub]]\n")

    graph = kb_view.build_graph(tmp_path)

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["routing/routing-map"]["entryPoint"] is True
    assert nodes["a/hub"]["entryPoint"] is False
    assert sum(node["pagerank"] for node in graph["nodes"]) == pytest.approx(
        1.0, abs=1e-4
    )
    assert nodes["a/hub"]["pagerank"] > nodes["a/leaf-one"]["pagerank"]
    assert nodes["a/hub"]["pagerank"] > nodes["routing/routing-map"]["pagerank"]


def test_search_pages_ranks_title_before_tag_before_body(tmp_path: Path) -> None:
    """Full-text search must stay deterministic and rank by match field."""
    _write_page(
        tmp_path,
        "a/kafka-cluster.md",
        "# Kafka Cluster\n\nBroker layout and retention settings.\n",
    )
    _write_page(
        tmp_path,
        "a/event-bus.md",
        "---\ntags: [kafka]\n---\n# Event Bus\n\nAsync topics.\n",
    )
    _write_page(
        tmp_path,
        "a/queue-backlog.md",
        "# Queue Backlog\n\nConsumer lag means the Kafka cluster is behind.\n",
    )
    _write_page(tmp_path, "a/unrelated.md", "# Unrelated\n\nNothing here.\n")

    graph, bodies = kb_view.build_viewer_state(tmp_path)
    results = kb_view.search_pages(graph, bodies, "kafka")

    assert [item["id"] for item in results] == [
        "a/kafka-cluster",
        "a/event-bus",
        "a/queue-backlog",
    ]
    assert [item["field"] for item in results] == ["title", "tag", "body"]
    body_hit = results[2]
    assert "Kafka" in body_hit["snippet"]
    assert kb_view.search_pages(graph, bodies, "   ") == []


def test_load_page_returns_frontmatter_and_rejects_traversal(tmp_path: Path) -> None:
    """Allowing a page id to escape knowledge/ would expose unrelated files."""
    _write_page(
        tmp_path,
        "domain/page.md",
        "---\nsource: raw/source.txt\nlast_verified: 2026-07-02\n---\n"
        "# Page title\n\nReadable body.\n",
    )
    (tmp_path / "secret.txt").write_text("do not expose", encoding="utf-8")

    page = kb_view.load_page(tmp_path, "domain/page")

    assert page == {
        "id": "domain/page",
        "label": "Page title",
        "path": "knowledge/domain/page.md",
        "metadata": {
            "source": "raw/source.txt",
            "last_verified": "2026-07-02",
        },
        "markdown": "# Page title\n\nReadable body.\n",
    }
    with pytest.raises(ValueError, match="Invalid page id"):
        kb_view.load_page(tmp_path, "../secret")
    with pytest.raises(FileNotFoundError):
        kb_view.load_page(tmp_path, "domain/missing")


@contextmanager
def _running_server(
    kb_root: Path,
    asset_dir: Path,
    *,
    opener: Callable[[Path], None] | None = None,
) -> Iterator[tuple[str, kb_view.ViewerServer]]:
    server = kb_view.create_server(
        kb_root=kb_root,
        asset_dir=asset_dir,
        host="127.0.0.1",
        port=0,
        opener=opener,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request_json(url: str, *, method: str = "GET") -> tuple[int, dict, object]:
    request = urllib.request.Request(url, method=method)
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return (
            response.status,
            dict(response.headers.items()),
            json.loads(response.read().decode("utf-8")),
        )


def _request_json_with_headers(
    url: str, *, method: str, headers: dict[str, str]
) -> tuple[int, dict, object]:
    request = urllib.request.Request(url, method=method, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return (
            response.status,
            dict(response.headers.items()),
            json.loads(response.read().decode("utf-8")),
        )


def test_server_exposes_graph_page_refresh_and_security_headers(
    tmp_path: Path,
) -> None:
    """Breaking the read-only API contract must fail through real HTTP."""
    _write_page(tmp_path, "domain/one.md", "# One\n")
    assets = tmp_path / "viewer-assets"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>viewer</h1>", encoding="utf-8")

    with _running_server(tmp_path, assets) as (base_url, _server):
        status, headers, graph = _request_json(f"{base_url}/api/graph")
        assert status == 200
        assert graph["stats"]["pages"] == 1
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "default-src 'self'" in headers["Content-Security-Policy"]

        status, _headers, page = _request_json(
            f"{base_url}/api/page?id=domain%2Fone"
        )
        assert status == 200
        assert page["id"] == "domain/one"

        status, _headers, error = _request_json(
            f"{base_url}/api/page?id=..%2Fsecret"
        )
        assert status == 400
        assert error == {"error": "Invalid page id"}

        _write_page(tmp_path, "domain/two.md", "# Two\n")
        status, _headers, refreshed = _request_json(
            f"{base_url}/api/refresh", method="POST"
        )
        assert status == 200
        assert refreshed["stats"]["pages"] == 2


def test_server_full_text_search_endpoint(tmp_path: Path) -> None:
    """/api/search must hit page bodies and refresh with the graph."""
    _write_page(
        tmp_path,
        "domain/one.md",
        "# One\n\nThe retention window is 7 days.\n",
    )
    assets = tmp_path / "viewer-assets"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>viewer</h1>", encoding="utf-8")

    with _running_server(tmp_path, assets) as (base_url, _server):
        status, _headers, payload = _request_json(
            f"{base_url}/api/search?q=retention"
        )
        assert status == 200
        assert payload["query"] == "retention"
        assert [item["id"] for item in payload["results"]] == ["domain/one"]
        assert payload["results"][0]["field"] == "body"
        assert "retention" in payload["results"][0]["snippet"]

        status, _headers, error = _request_json(f"{base_url}/api/search")
        assert status == 400
        assert error == {"error": "Missing search query"}

        _write_page(
            tmp_path,
            "domain/two.md",
            "# Two\n\nDunning flow retries three times.\n",
        )
        status, _headers, _refreshed = _request_json(
            f"{base_url}/api/refresh", method="POST"
        )
        assert status == 200
        status, _headers, payload = _request_json(
            f"{base_url}/api/search?q=dunning"
        )
        assert status == 200
        assert [item["id"] for item in payload["results"]] == ["domain/two"]


def test_server_serves_only_configured_static_assets(tmp_path: Path) -> None:
    """Static traversal must not read arbitrary files outside the viewer bundle."""
    (tmp_path / "knowledge").mkdir()
    assets = tmp_path / "viewer-assets"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>viewer</h1>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("do not expose", encoding="utf-8")

    with _running_server(tmp_path, assets) as (base_url, _server):
        with urllib.request.urlopen(base_url, timeout=5) as response:
            assert response.status == 200
            assert response.read().decode("utf-8") == "<h1>viewer</h1>"

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"{base_url}/../secret.txt", timeout=5)
        assert exc_info.value.code == 404


def test_server_opens_only_valid_pages_after_explicit_viewer_action(
    tmp_path: Path,
) -> None:
    """A cross-origin form-style POST must not launch arbitrary local files."""
    page_path = _write_page(tmp_path, "domain/one.md", "# One\n").resolve()
    assets = tmp_path / "viewer-assets"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>viewer</h1>", encoding="utf-8")
    opened: list[Path] = []

    with _running_server(tmp_path, assets, opener=opened.append) as (
        base_url,
        _server,
    ):
        status, _headers, payload = _request_json(
            f"{base_url}/api/open?id=domain%2Fone", method="POST"
        )
        assert status == 403
        assert payload == {"error": "Viewer action header required"}
        assert opened == []

        status, _headers, payload = _request_json_with_headers(
            f"{base_url}/api/open?id=domain%2Fone",
            method="POST",
            headers={"X-KB-Viewer": "1"},
        )
        assert status == 200
        assert payload == {"ok": True}
        assert opened == [page_path]


def test_cli_starts_real_server_on_random_port_without_browser(
    tmp_path: Path,
) -> None:
    """Removing the executable CLI path must break a real HTTP smoke test."""
    _write_page(tmp_path, "domain/one.md", "# One\n")
    assets = tmp_path / "viewer-assets"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>viewer</h1>", encoding="utf-8")

    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(kb_view.__file__).resolve()),
            "--kb-root",
            str(tmp_path),
            "--asset-dir",
            str(assets),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--no-browser",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert process.stdout is not None
        first_line = process.stdout.readline().strip()
        match = re.fullmatch(r"Knowledge graph: (http://127\.0\.0\.1:\d+/)", first_line)
        assert match, first_line
        with urllib.request.urlopen(match.group(1), timeout=5) as response:
            assert response.read().decode("utf-8") == "<h1>viewer</h1>"
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_cli_fails_cleanly_when_viewer_assets_are_missing(tmp_path: Path) -> None:
    """A missing static bundle should produce a useful startup error."""
    result = subprocess.run(
        [
            sys.executable,
            str(Path(kb_view.__file__).resolve()),
            "--kb-root",
            str(tmp_path),
            "--asset-dir",
            str(tmp_path / "missing"),
            "--no-browser",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
    )
    assert result.returncode == 2
    assert "Viewer assets not found" in result.stderr


def test_shipped_viewer_bundle_is_served_offline(tmp_path: Path) -> None:
    """Removing a local UI asset must break the no-CDN deployment contract."""
    (tmp_path / "knowledge").mkdir()
    assets = Path(kb_view.__file__).with_name("kb_viewer")

    with _running_server(tmp_path, assets) as (base_url, _server):
        expected = {
            "": ("text/html", 500),
            "app.css": ("text/css", 1_000),
            "app.js": ("javascript", 5_000),
            "vendor/vis-network.min.js": ("javascript", 100_000),
        }
        for rel, (content_type, minimum_bytes) in expected.items():
            with urllib.request.urlopen(f"{base_url}/{rel}", timeout=5) as response:
                body = response.read()
                assert response.status == 200
                assert content_type in response.headers["Content-Type"]
                assert len(body) >= minimum_bytes

    css = (assets / "app.css").read_text(encoding="utf-8")
    assert "[hidden]" in css
    assert "display: none !important" in css
    assert ".topbar .sidebar-toggle" in css


def test_background_cli_is_idempotent_and_can_report_and_stop(
    tmp_path: Path,
) -> None:
    """Repeated !view launches must reuse one server instead of leaking processes."""
    _write_page(tmp_path, "domain/one.md", "# One\n")
    assets = tmp_path / "viewer-assets"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>viewer</h1>", encoding="utf-8")
    base_command = [
        sys.executable,
        str(Path(kb_view.__file__).resolve()),
        "--kb-root",
        str(tmp_path),
        "--asset-dir",
        str(assets),
        "--no-browser",
    ]

    first = subprocess.run(
        [*base_command, "--background"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    try:
        assert first.returncode == 0, first.stderr
        first_url = first.stdout.strip().removeprefix("Knowledge graph: ")
        assert re.fullmatch(r"http://127\.0\.0\.1:\d+/", first_url)

        second = subprocess.run(
            [*base_command, "--background"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        assert second.returncode == 0, second.stderr
        assert second.stdout.strip() == f"Knowledge graph: {first_url}"

        status = subprocess.run(
            [*base_command, "--status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        assert status.returncode == 0
        assert status.stdout.strip() == f"Knowledge graph: {first_url}"

        with urllib.request.urlopen(first_url, timeout=5) as response:
            assert response.status == 200
    finally:
        stopped = subprocess.run(
            [*base_command, "--stop"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        assert stopped.returncode == 0, stopped.stderr
        assert stopped.stdout.strip() == "Knowledge graph stopped."

    status = subprocess.run(
        [*base_command, "--status"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert status.returncode == 1
    assert status.stdout.strip() == "Knowledge graph is not running."
