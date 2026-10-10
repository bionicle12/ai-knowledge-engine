"""Tests for the local knowledge-graph viewer."""
from __future__ import annotations

import json
import os
import random
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

import kb_common as kbc
import kb_view
import pytest

VIEWER_HEADERS = {"X-KB-Viewer": "1"}


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
        "stale": False,
        "staleReason": "permanent",
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
        "rules": {"staleWarningDays": 30},
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
        status, _headers, refreshed = _request_json_with_headers(
            f"{base_url}/api/refresh", method="POST", headers=VIEWER_HEADERS
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
        status, _headers, _refreshed = _request_json_with_headers(
            f"{base_url}/api/refresh", method="POST", headers=VIEWER_HEADERS
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


def _private_runtime_env(tmp_path: Path) -> dict[str, str]:
    """Keep the viewer state file of a test run out of the real runtime dir."""
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    return {**os.environ, "XDG_RUNTIME_DIR": str(runtime), "TMPDIR": str(runtime)}


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
    env = _private_runtime_env(tmp_path)

    first = subprocess.run(
        [*base_command, "--background"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        env=env,
    )
    # Remember the server's pid: a failed --stop must not leave it running.
    pids = [
        json.loads(state.read_text(encoding="utf-8"))["pid"]
        for state in (tmp_path / "runtime").rglob("*.json")
    ]
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
            env=env,
        )
        assert second.returncode == 0, second.stderr
        assert second.stdout.strip() == f"Knowledge graph: {first_url}"

        status = subprocess.run(
            [*base_command, "--status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            env=env,
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
            env=env,
        )
        if stopped.returncode != 0:
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
        assert stopped.returncode == 0, stopped.stderr
        assert stopped.stdout.strip() == "Knowledge graph stopped."

    status = subprocess.run(
        [*base_command, "--status"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        env=env,
    )
    assert status.returncode == 1
    assert status.stdout.strip() == "Knowledge graph is not running."


def test_exploration_pairs_two_components_low_overlap(tmp_path: Path) -> None:
    _write_page(
        tmp_path,
        "domain/alpha.md",
        "---\ntags: [alpha]\n---\n# Alpha\n\nStandalone.\n",
    )
    _write_page(
        tmp_path,
        "projects/beta.md",
        "---\ntags: [beta]\n---\n# Beta\n\nAlso standalone.\n",
    )
    graph = kb_view.build_graph(tmp_path)
    assert kb_view.undirected_components(graph) == [
        ["domain/alpha"],
        ["projects/beta"],
    ]
    pairs = kb_view.exploration_pairs(graph)
    assert len(pairs) == 1
    assert pairs[0]["a"] == "domain/alpha"
    assert pairs[0]["b"] == "projects/beta"
    assert pairs[0]["overlap"] == 0.0
    assert pairs[0]["reason"] == "disconnected-components"
    assert "[[domain/alpha]]" in pairs[0]["prompt"]


def test_exploration_pairs_high_overlap_filtered(tmp_path: Path) -> None:
    _write_page(
        tmp_path,
        "domain/one.md",
        "---\ntags: [shared, extra]\n---\n# One\n\nA.\n",
    )
    _write_page(
        tmp_path,
        "domain/two.md",
        "---\ntags: [shared, extra]\n---\n# Two\n\nB.\n",
    )
    graph = kb_view.build_graph(tmp_path)
    assert kb_view.overlap_score(graph["nodes"][0], graph["nodes"][1]) == 1.0
    assert kb_view.exploration_pairs(graph) == []


def test_exploration_pairs_empty_when_linked(tmp_path: Path) -> None:
    _write_page(tmp_path, "domain/a.md", "# A\n\nSee [[domain/b]].\n")
    _write_page(tmp_path, "domain/b.md", "# B\n\nSee [[domain/a]].\n")
    graph = kb_view.build_graph(tmp_path)
    assert kb_view.exploration_pairs(graph) == []


# ---------------------------------------------------------------------------
# Audit 2026-09 regressions (MV11-MV21, D9)
# ---------------------------------------------------------------------------


def _viewer_assets(tmp_path: Path) -> Path:
    assets = tmp_path / "viewer-assets"
    assets.mkdir(exist_ok=True)
    (assets / "index.html").write_text("<h1>viewer</h1>", encoding="utf-8")
    return assets


def test_foreign_host_header_is_refused(tmp_path: Path) -> None:
    """MV11: a DNS-rebinding page reaches the viewer under its own host name."""
    _write_page(tmp_path, "domain/one.md", "# One\n\nsecret plan\n")
    opened: list[Path] = []

    with _running_server(
        tmp_path, _viewer_assets(tmp_path), opener=opened.append
    ) as (base_url, server):
        port = server.server_address[1]
        for path in ("/api/graph", "/api/search?q=secret", "/api/page?id=domain%2Fone", "/"):
            status, _headers, payload = _request_json_with_headers(
                f"{base_url}{path}",
                method="GET",
                headers={"Host": f"attacker.example:{port}"},
            )
            assert status == 403, path
            assert payload == {"error": "Forbidden host"}
        status, _headers, _payload = _request_json_with_headers(
            f"{base_url}/api/open?id=domain%2Fone",
            method="POST",
            headers={**VIEWER_HEADERS, "Host": f"attacker.example:{port}"},
        )
        assert status == 403
        assert opened == []
        # Wrong port (another local service's origin) is refused as well.
        status, _headers, _payload = _request_json_with_headers(
            f"{base_url}/api/graph", method="GET", headers={"Host": "127.0.0.1:1"}
        )
        assert status == 403

        for host in (f"localhost:{port}", f"127.0.0.1:{port}"):
            status, _headers, graph = _request_json_with_headers(
                f"{base_url}/api/graph", method="GET", headers={"Host": host}
            )
            assert status == 200, host
            assert graph["stats"]["pages"] == 1


def test_cross_origin_post_is_refused(tmp_path: Path) -> None:
    """MV11/MV17: a POST carrying a foreign Origin must not act."""
    _write_page(tmp_path, "domain/one.md", "# One\n")
    opened: list[Path] = []

    with _running_server(
        tmp_path, _viewer_assets(tmp_path), opener=opened.append
    ) as (base_url, server):
        port = server.server_address[1]
        for path in ("/api/open?id=domain%2Fone", "/api/refresh"):
            status, _headers, payload = _request_json_with_headers(
                f"{base_url}{path}",
                method="POST",
                headers={**VIEWER_HEADERS, "Origin": "http://attacker.example"},
            )
            assert status == 403, path
            assert payload == {"error": "Forbidden origin"}
        assert opened == []

        status, _headers, payload = _request_json_with_headers(
            f"{base_url}/api/open?id=domain%2Fone",
            method="POST",
            headers={**VIEWER_HEADERS, "Origin": f"http://127.0.0.1:{port}"},
        )
        assert status == 200
        assert len(opened) == 1


def test_refresh_requires_the_viewer_header(tmp_path: Path) -> None:
    """MV17: a cross-site simple POST must not trigger a full rebuild."""
    _write_page(tmp_path, "domain/one.md", "# One\n")

    with _running_server(tmp_path, _viewer_assets(tmp_path)) as (base_url, _server):
        status, _headers, payload = _request_json(
            f"{base_url}/api/refresh", method="POST"
        )
        assert status == 403
        assert payload == {"error": "Viewer action header required"}

        status, _headers, graph = _request_json_with_headers(
            f"{base_url}/api/refresh", method="POST", headers=VIEWER_HEADERS
        )
        assert status == 200
        assert graph["stats"]["pages"] == 1

    app_js = (Path(kb_view.__file__).with_name("kb_viewer") / "app.js").read_text(
        encoding="utf-8"
    )
    refresh_call = re.search(r'request\("/api/refresh",\s*\{(.*?)\}\);', app_js, re.S)
    assert refresh_call, "app.js must POST /api/refresh"
    assert '"X-KB-Viewer": "1"' in refresh_call.group(1)


def _synthetic_graph(
    edges: dict[str, list[str]],
    tags: dict[str, list[str]] | None = None,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    tags = tags or {}
    labels = labels or {}
    inbound: dict[str, set[str]] = {page: set() for page in edges}
    for page, targets in edges.items():
        for target in targets:
            if target != page:
                inbound[target].add(page)
    order = sorted(edges)
    ranks = kb_view._pagerank(order, {page: set(edges[page]) for page in order})
    return {
        "nodes": [
            {
                "id": page,
                "label": labels.get(page, page),
                "tags": tags.get(page, []),
                "outbound": sorted(set(edges[page])),
                "inbound": sorted(inbound[page]),
                "pagerank": ranks[page],
            }
            for page in order
        ]
    }


def _reference_exploration_pairs(
    graph: dict[str, Any], *, max_pairs: int = 2, overlap_max: float = 0.8
) -> list[dict[str, Any]]:
    """The pre-0.16 O(n²·(n+e)) algorithm, kept as the output-contract oracle."""
    nodes = {node["id"]: node for node in graph.get("nodes") or []}
    if len(nodes) < 2 or max_pairs <= 0:
        return []

    def rep(comp: list[str]) -> str:
        return max(comp, key=lambda p: (float(nodes[p].get("pagerank") or 0.0), p))

    def pair(a: str, b: str, reason: str) -> dict[str, Any] | None:
        if a == b:
            return None
        score = kb_view.overlap_score(nodes[a], nodes[b])
        if score >= overlap_max:
            return None
        left, right = sorted((a, b))
        return {
            "a": left,
            "b": right,
            "overlap": round(score, 4),
            "reason": reason,
            "prompt": f"What connects [[{left}]] and [[{right}]] that the graph does not show?",
        }

    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(item: dict[str, Any] | None) -> None:
        if item is None or (item["a"], item["b"]) in seen:
            return
        seen.add((item["a"], item["b"]))
        pairs.append(item)

    components = [c for c in kb_view.undirected_components(graph) if c]
    if len(components) >= 2:
        ranked = sorted(components, key=lambda comp: (-len(comp), comp[0]))
        for i, left in enumerate(ranked):
            for right in ranked[i + 1 :]:
                add(pair(rep(left), rep(right), "disconnected-components"))
                if len(pairs) >= max_pairs:
                    return pairs
    outbound = {n["id"]: list(n.get("outbound") or []) for n in graph["nodes"]}

    def path(start: str, goal: str) -> bool:
        seen_nodes, stack = {start}, [start]
        while stack:
            for nxt in outbound.get(stack.pop()) or []:
                if nxt == goal:
                    return True
                if nxt not in seen_nodes:
                    seen_nodes.add(nxt)
                    stack.append(nxt)
        return False

    ids = sorted(nodes)
    for i, src in enumerate(ids):
        for dst in ids[i + 1 :]:
            if path(src, dst) or path(dst, src):
                continue
            add(pair(src, dst, "no-directed-path"))
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def test_exploration_pairs_keeps_the_output_contract_on_random_graphs() -> None:
    """MV12: the SCC rewrite must return exactly what the old search did."""
    rng = random.Random(20260923)
    pool = ["alpha", "beta", "gamma"]
    for _ in range(400):
        count = rng.randint(2, 11)
        ids = [f"p{i:02d}" for i in range(count)]
        density = rng.choice([0.05, 0.15, 0.3, 0.6])
        edges = {
            page: [other for other in ids if rng.random() < density]
            for page in ids
        }
        tags = {page: rng.sample(pool, rng.randint(0, 2)) for page in ids}
        labels = {page: rng.choice(["Kafka cluster", "Kafka broker", page]) for page in ids}
        graph = _synthetic_graph(edges, tags, labels)
        for max_pairs in (1, 2, 5):
            # 0.8 is the default; 1.0 / 1.5 keep identical tag sets as pairs,
            # 0.0 rejects everything (the twin shortcut must agree each time).
            for overlap_max in (0.8, 0.0, 0.5, 1.0, 1.5):
                assert kb_view.exploration_pairs(
                    graph, max_pairs=max_pairs, overlap_max=overlap_max
                ) == _reference_exploration_pairs(
                    graph, max_pairs=max_pairs, overlap_max=overlap_max
                ), (edges, tags, labels, overlap_max)


def test_exploration_pairs_scales_to_large_linked_graphs() -> None:
    """MV12: a fully related graph used to cost one DFS per page pair."""
    ids = [f"n{i:04d}" for i in range(1500)]
    edges = {page: [ids[i + 1]] if i + 1 < len(ids) else [] for i, page in enumerate(ids)}
    # Back links make strongly connected blocks inside the chain.
    edges[ids[40]].append(ids[10])
    edges[ids[900]].append(ids[700])
    graph = _synthetic_graph(edges)

    started = time.monotonic()
    assert kb_view.exploration_pairs(graph) == []
    assert time.monotonic() - started < 5

    # A side branch off n0005 is unrelated to every page after n0005.
    edges["zz-side"] = []
    edges[ids[5]].append("zz-side")
    graph = _synthetic_graph(edges)
    started = time.monotonic()
    pairs = kb_view.exploration_pairs(graph)
    assert time.monotonic() - started < 5
    assert [(p["a"], p["b"], p["reason"]) for p in pairs] == [
        ("n0006", "zz-side", "no-directed-path"),
        ("n0007", "zz-side", "no-directed-path"),
    ]


def test_exploration_pairs_is_bounded_when_every_pair_is_a_near_twin() -> None:
    """MV12 (residual): 2001 unlinked pages sharing 9 of their 10 tags (overlap
    0.82, rejected) were scored pair by pair — ~9 s, ~1 min at 5000 pages."""
    ids = [f"n{i:04d}" for i in range(2001)]
    shared = [f"t{i}" for i in range(9)]
    graph = _synthetic_graph(
        {page: [] for page in ids}, tags={page: [*shared, f"own-{page}"] for page in ids}
    )

    started = time.monotonic()
    assert kb_view.exploration_pairs(graph) == []
    assert time.monotonic() - started < 3


def test_refresh_reparses_only_changed_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MV13: /api/refresh used to re-parse every page of the base."""
    _write_page(tmp_path, "domain/a.md", "# A\n\n[[domain/b]]\n")
    _write_page(tmp_path, "domain/b.md", "# B\n")
    parsed: list[str] = []
    real = kbc.read_frontmatter_file

    def counting(path: Path | str) -> tuple[dict, str]:
        parsed.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(kbc, "read_frontmatter_file", counting)
    server = kb_view.create_server(
        kb_root=tmp_path, asset_dir=_viewer_assets(tmp_path), port=0
    )
    try:
        assert sorted(parsed) == ["a.md", "b.md"]
        parsed.clear()
        _write_page(tmp_path, "domain/b.md", "# B changed\n\nNew body text.\n")
        _write_page(tmp_path, "domain/c.md", "# C\n")
        graph = server.refresh()
        assert sorted(parsed) == ["b.md", "c.md"]
        labels = {node["id"]: node["label"] for node in graph["nodes"]}
        assert labels == {"domain/a": "A", "domain/b": "B changed", "domain/c": "C"}
        assert [r["id"] for r in server.search("new body")] == ["domain/b"]

        parsed.clear()
        (tmp_path / "knowledge" / "domain" / "c.md").unlink()
        graph = server.refresh()
        assert parsed == []
        assert [node["id"] for node in graph["nodes"]] == ["domain/a", "domain/b"]
    finally:
        server.server_close()


def test_initial_layout_is_time_boxed_for_large_graphs() -> None:
    """MV13: 2000 nodes spent 40+ s in physics before the graph was usable."""
    app_js = (Path(kb_view.__file__).with_name("kb_viewer") / "app.js").read_text(
        encoding="utf-8"
    )
    assert re.search(r"const LAYOUT_BUDGET_MS = \d+;", app_js)
    assert "stopSimulation()" in app_js
    assert re.search(r"improvedLayout:\s*[^,\n]*IMPROVED_LAYOUT_MAX_NODES", app_js)


def test_stale_flag_uses_the_shared_lint_rule(tmp_path: Path) -> None:
    """MV14: the viewer's 180-day rule disagreed with kb_lint's."""
    old = (date.today() - timedelta(days=400)).isoformat()
    recent = (date.today() - timedelta(days=5)).isoformat()
    pages = {
        "domain/old.md": f"---\nlast_verified: {old}\n---\n# Old\n",
        "domain/permanent.md": f"---\nlifecycle: permanent\nlast_verified: {old}\n---\n# P\n",
        "decisions/choice.md": f"---\nlifecycle: evolving\nlast_verified: {old}\n---\n# D\n",
        "domain/undated.md": "# Undated\n",
        "domain/re-extracted.md": (
            f"---\nlast_verified: {old}\nextracted_at: {recent}\n---\n# R\n"
        ),
        "routing/generated.md": (
            f"---\ngenerated_by: kb_route.py\nlast_verified: {old}\n---\n# G\n"
        ),
        "_archive/gone.md": f"---\nlast_verified: {old}\n---\n# Gone\n",
    }
    for rel, text in pages.items():
        _write_page(tmp_path, rel, text)

    nodes = {node["id"]: node for node in kb_view.build_graph(tmp_path)["nodes"]}
    assert {page for page, node in nodes.items() if node["stale"]} == {"domain/old"}
    assert nodes["domain/old"]["staleReason"] == (
        f"last_verified {old} is 400 days old (threshold: 30)"
    )
    assert nodes["decisions/choice"]["staleReason"] == "permanent"
    assert nodes["domain/undated"]["staleReason"] == "no date"
    assert nodes["routing/generated"]["staleReason"] == "generated"
    assert nodes["_archive/gone"]["staleReason"] == "archived"

    (tmp_path / "kb.config.yml").write_text(
        "lifecycle:\n  stale_warning_days: 500\n", encoding="utf-8"
    )
    nodes = {node["id"]: node for node in kb_view.build_graph(tmp_path)["nodes"]}
    assert not any(node["stale"] for node in nodes.values())

    # A broken config must not take the viewer down: code defaults apply.
    (tmp_path / "kb.config.yml").write_text("lifecycle: [unclosed\n", encoding="utf-8")
    nodes = {node["id"]: node for node in kb_view.build_graph(tmp_path)["nodes"]}
    assert nodes["domain/old"]["stale"] is True

    app_js = (Path(kb_view.__file__).with_name("kb_viewer") / "app.js").read_text(
        encoding="utf-8"
    )
    assert "STALE_MS" not in app_js
    assert "node.stale === true" in app_js
    assert "staleReason" in app_js


def test_generated_and_archived_pages_are_not_orphans(tmp_path: Path) -> None:
    """D9: kb_lint skips generated and _archive/ pages in the orphan check."""
    _write_page(tmp_path, "domain/lonely.md", "# Lonely\n")
    _write_page(
        tmp_path,
        "domain/assets-overview.md",
        "---\ngenerated_by: kb_route.py\n---\n# Overview\n",
    )
    _write_page(tmp_path, "_archive/old-plan.md", "# Old plan\n")

    graph = kb_view.build_graph(tmp_path)

    assert graph["diagnostics"]["orphans"] == ["domain/lonely"]
    assert graph["stats"]["orphans"] == 1


def test_list_frontmatter_does_not_break_the_viewer(tmp_path: Path) -> None:
    """MV15: a list frontmatter used to crash build_viewer_state."""
    _write_page(tmp_path, "domain/list.md", "---\n- a\n- b\n---\n# Listed\n")
    _write_page(tmp_path, "domain/ok.md", "---\ntags: [x]\n---\n# Ok\n")

    nodes = {node["id"]: node for node in kb_view.build_graph(tmp_path)["nodes"]}

    assert set(nodes) == {"domain/list", "domain/ok"}
    assert nodes["domain/list"]["tags"] == []
    assert kb_view.load_page(tmp_path, "domain/list")["metadata"] == {}


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlinks_leaving_knowledge_are_not_indexed(tmp_path: Path) -> None:
    """MV16: /api/page refused the link, but the graph and search exposed it."""
    (tmp_path / ".env").write_text("SECRET_TOKEN=supersecret\n", encoding="utf-8")
    _write_page(tmp_path, "domain/real.md", "# Real\n\nInside the base.\n")
    domain = tmp_path / "knowledge" / "domain"
    (domain / "leak.md").symlink_to(tmp_path / ".env")
    (domain / "alias.md").symlink_to(domain / "real.md")
    (domain / "dangling.md").symlink_to(domain / "missing.md")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "notes.md").write_text("# Notes\n\nsupersecret too\n", encoding="utf-8")
    (tmp_path / "knowledge" / "linked-folder").symlink_to(
        outside, target_is_directory=True
    )

    graph, bodies = kb_view.build_viewer_state(tmp_path)

    assert sorted(node["id"] for node in graph["nodes"]) == [
        "domain/alias",
        "domain/real",
    ]
    assert "supersecret" not in json.dumps(graph)
    assert kb_view.search_pages(graph, bodies, "supersecret") == []


def test_alias_bomb_frontmatter_stays_small_and_fast(tmp_path: Path) -> None:
    """MV19: a 345-byte alias bomb made /api/page take 16 s and 58 MB."""
    levels = ["a: &a [lol, lol, lol, lol, lol, lol, lol, lol, lol]"]
    for prev, name in zip("abcdef", "bcdefg"):
        levels.append(f"{name}: &{name} [" + ", ".join([f"*{prev}"] * 9) + "]")
    _write_page(
        tmp_path, "domain/bomb.md", "---\n" + "\n".join(levels) + "\n---\n# Bomb\n"
    )

    started = time.monotonic()
    page = kb_view.load_page(tmp_path, "domain/bomb")
    graph = kb_view.build_graph(tmp_path)
    assert time.monotonic() - started < 5
    assert page["metadata"] == {}
    assert len(json.dumps(page)) < 10_000
    assert [node["id"] for node in graph["nodes"]] == ["domain/bomb"]


def test_search_snippet_contains_the_match_after_casefold_expansion(
    tmp_path: Path,
) -> None:
    """MV21: ``ß`` → ``ss`` shifted the snippet window past the keyword."""
    _write_page(
        tmp_path,
        "domain/strasse.md",
        "# Streets\n\n" + "Straße " * 200 + "the keyword lives here.\n",
    )
    graph, bodies = kb_view.build_viewer_state(tmp_path)

    results = kb_view.search_pages(graph, bodies, "KEYWORD")

    assert [item["id"] for item in results] == ["domain/strasse"]
    assert "the keyword lives here." in results[0]["snippet"]
    assert results[0]["snippet"].startswith("…")
    # A needle that itself expands (ß → ss) maps back to the original text.
    results = kb_view.search_pages(graph, bodies, "STRASSE the")
    assert "Straße the keyword" in results[0]["snippet"]


def _in_memory_base(count: int, body: Callable[[int], str]) -> tuple[dict, dict]:
    bodies = {f"domain/p{i:05d}": body(i) for i in range(count)}
    graph = {
        "nodes": [
            {"id": page_id, "label": page_id, "path": f"knowledge/{page_id}.md",
             "group": "domain", "tags": []}
            for page_id in bodies
        ]
    }
    return graph, bodies


def test_search_builds_snippets_only_for_returned_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MV13/MV21: every German page paid a Python walk to the match on each
    keystroke, although only 30 results are sent (5000 pages: 3.2 s)."""
    lorem = "lorem ipsum dolor sit amet consectetur adipiscing elit " * 30
    graph, bodies = _in_memory_base(5000, lambda i: f"{lorem}Straße {i}\n")
    folded = {page_id: body.casefold() for page_id, body in bodies.items()}
    calls: list[int] = []
    real = kb_view._unfolded_index

    def counting(text: str, folded_index: int) -> int:
        calls.append(folded_index)
        return real(text, folded_index)

    monkeypatch.setattr(kb_view, "_unfolded_index", counting)
    started = time.monotonic()
    results = kb_view.search_pages(graph, bodies, "STRASSE", folded=folded)
    elapsed = time.monotonic() - started

    assert len(results) == 30
    assert len(calls) <= 2 * 30
    assert elapsed < 1.0
    assert all("Straße" in item["snippet"] for item in results)
    assert results[0]["matches"] == 1


def test_unfolded_index_matches_a_per_character_walk() -> None:
    """MV21: the chunked mapping must agree with the plain per-character one."""

    def reference(text: str, folded_index: int) -> int:
        position = 0
        for offset, char in enumerate(text):
            position += len(char.casefold())
            if position > folded_index:
                return offset
        return len(text)

    rng = random.Random(7)
    alphabet = "abcXYZ ßﬁİŉΐẞ"
    for _ in range(40):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 3000)))
        folded_length = len(text.casefold())
        probes = {0, folded_length - 1, folded_length, folded_length + 5}
        probes |= {rng.randrange(folded_length + 1) for _ in range(30)}
        for probe in sorted(p for p in probes if p >= 0):
            assert kb_view._unfolded_index(text, probe) == reference(text, probe)


def test_exploration_pairs_skips_pages_sharing_one_tag_set() -> None:
    """MV12: a hub linking thousands of pages that all carry the same tags
    cost one overlap check per pair (5000 leaves: 32 s) to return nothing."""
    leaves = [f"leaf{i:05d}" for i in range(3000)]
    edges: dict[str, list[str]] = {"hub": list(leaves), **{leaf: [] for leaf in leaves}}
    tags = {page: ["kb"] for page in edges}
    graph = _synthetic_graph(edges, tags)
    started = time.monotonic()
    assert kb_view.exploration_pairs(graph) == []
    assert time.monotonic() - started < 3

    # The same without links: 3000 one-page components with one tag set.
    lonely = _synthetic_graph({leaf: [] for leaf in leaves}, tags)
    started = time.monotonic()
    assert kb_view.exploration_pairs(lonely) == []
    assert time.monotonic() - started < 3

    # One differently tagged leaf still yields the pairs the old search found.
    small = {"hub": leaves[:60], **{leaf: [] for leaf in leaves[:60]}}
    small_tags = {page: ["kb"] for page in small}
    small_tags[leaves[42]] = ["other"]
    graph = _synthetic_graph(small, small_tags)
    for max_pairs in (1, 2, 5):
        assert kb_view.exploration_pairs(
            graph, max_pairs=max_pairs
        ) == _reference_exploration_pairs(graph, max_pairs=max_pairs)
    assert kb_view.exploration_pairs(graph)[0]["b"] == leaves[42]


def _reference_pagerank(
    order: list[str], outbound: dict[str, set[str]]
) -> dict[str, float]:
    """The pre-0.16 id-keyed PageRank, kept as the oracle for the list rewrite."""
    count = len(order)
    links = {page: sorted(t for t in outbound[page] if t != page) for page in order}
    rank = {page: 1.0 / count for page in order}
    for _ in range(60):
        dangling = sum(rank[page] for page in order if not links[page])
        base = 0.15 / count + 0.85 * dangling / count
        next_rank = dict.fromkeys(order, base)
        for page in order:
            if links[page]:
                share = 0.85 * rank[page] / len(links[page])
                for target in links[page]:
                    next_rank[target] += share
        rank = next_rank
    return {page: round(value, 6) for page, value in rank.items()}


def test_pagerank_rewrite_keeps_the_same_ranks() -> None:
    """MV13: PageRank runs on every refresh; the faster version is exact."""
    rng = random.Random(11)
    for _ in range(150):
        order = [f"p{i:02d}" for i in range(rng.randint(1, 40))]
        density = rng.choice([0.02, 0.1, 0.4])
        outbound = {page: {t for t in order if rng.random() < density} for page in order}
        assert kb_view._pagerank(order, outbound) == _reference_pagerank(order, outbound)


def test_refresh_reuses_links_and_fields_of_unchanged_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MV13: a warm refresh redid wikilink extraction for every page."""
    for index in range(5):
        _write_page(tmp_path, f"domain/p{index}.md", f"# P{index}\n\n[[p{index + 1}]]\n")
    extracted: list[str] = []
    real = kbc.extract_wikilinks_with_context

    def counting(text: str) -> list[tuple[str, str]]:
        extracted.append(text)
        return real(text)

    monkeypatch.setattr(kbc, "extract_wikilinks_with_context", counting)
    cache: kb_view.PageCache = {}
    cold, _ = kb_view.build_viewer_state(tmp_path, cache=cache)
    assert len(extracted) == 5
    extracted.clear()
    _write_page(tmp_path, "domain/p2.md", "# P2 changed\n\n[[p0]]\n")
    warm, _ = kb_view.build_viewer_state(tmp_path, cache=cache)

    assert len(extracted) == 1
    assert warm == kb_view.build_viewer_state(tmp_path)[0]
    assert {edge["to"] for edge in warm["edges"] if edge["from"] == "domain/p2"} == {
        "domain/p0"
    }
    assert warm["stats"]["broken"] == cold["stats"]["broken"] == 1  # [[p5]]


def test_repeated_long_anchor_cannot_inflate_viewer_responses(tmp_path: Path) -> None:
    """MV19: 99 aliases of one 100 KB string made every /api/graph 10 MB."""
    long_value = "x" * 100_000
    tag_refs = ", ".join(["*a"] * 60)
    source_refs = ", ".join(["*a"] * 37)  # 99 aliases: under kbc.MAX_YAML_ALIASES
    _write_page(
        tmp_path,
        "domain/amp.md",
        f'---\na: &a "{long_value}"\ntags: [{tag_refs}]\nimportance: *a\n'
        f"lifecycle: *a\nsources: [{source_refs}]\nscore: .nan\n---\n# Amp\n",
    )
    summary = "A long but honest summary. " * 200
    _write_page(
        tmp_path,
        "domain/normal.md",
        f"---\ntags: [kafka, streaming]\nimportance: 4\nsummary: {summary.strip()}\n"
        "---\n# Normal\n\nBody.\n",
    )
    file_size = (tmp_path / "knowledge" / "domain" / "amp.md").stat().st_size

    graph = kb_view.build_graph(tmp_path)
    page = kb_view.load_page(tmp_path, "domain/amp")

    graph_json = json.dumps(graph, ensure_ascii=False, allow_nan=False)
    assert len(graph_json) < 30_000
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert len(nodes["domain/amp"]["tags"]) <= kb_view.MAX_TAGS
    assert all(len(tag) <= kb_view.MAX_TAG_CHARS for tag in nodes["domain/amp"]["tags"])
    assert len(nodes["domain/amp"]["importance"]) <= kb_view.MAX_FIELD_CHARS
    page_json = json.dumps(page, ensure_ascii=False, allow_nan=False)
    assert len(page_json) < 2 * file_size
    assert page["metadata"]["a"] == long_value  # the file's own text is kept

    # Ordinary pages lose nothing.
    assert nodes["domain/normal"]["tags"] == ["kafka", "streaming"]
    assert nodes["domain/normal"]["importance"] == 4
    normal = kb_view.load_page(tmp_path, "domain/normal")
    assert normal["metadata"]["summary"] == summary.strip()
    assert normal["metadata"]["tags"] == ["kafka", "streaming"]


def test_health_chip_tooltips_describe_the_lint_rules(tmp_path: Path) -> None:
    """MV14: the stale chip still promised the removed 180-day rule."""
    viewer = Path(kb_view.__file__).with_name("kb_viewer")
    index_html = (viewer / "index.html").read_text(encoding="utf-8")
    app_js = (viewer / "app.js").read_text(encoding="utf-8")

    assert "180" not in index_html
    chips = dict(re.findall(r'data-health="(\w+)"\s+aria-pressed="false"\s+title="([^"]+)"', index_html))
    assert "lifecycle.stale_warning_days" in chips["stale"]
    assert "kb_lint" in chips["stale"]
    assert "_archive/" in chips["orphans"] and "generated" in chips["orphans"]
    assert "rules?.staleWarningDays" in app_js

    _write_page(tmp_path, "domain/a.md", "# A\n")
    assert kb_view.build_graph(tmp_path)["rules"] == {"staleWarningDays": 30}
    (tmp_path / "kb.config.yml").write_text(
        "lifecycle:\n  stale_warning_days: 90\n", encoding="utf-8"
    )
    assert kb_view.build_graph(tmp_path)["rules"] == {"staleWarningDays": 90}


@pytest.fixture
def private_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    return runtime


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_state_file_is_private(tmp_path: Path, private_runtime: Path) -> None:
    """MV18: the shutdown token sat in a world-readable file in shared /tmp."""
    state_file = kb_view.state_file_for_root(tmp_path)
    assert state_file.parent.parent == private_runtime

    kb_view._write_state(
        state_file, url="http://127.0.0.1:1/", token="t0k3n", kb_root=tmp_path
    )

    assert stat.S_IMODE(state_file.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
    assert kb_view._read_state(state_file)["token"] == "t0k3n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_state_dir_without_runtime_dir_is_per_user_and_tightened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MV18: without XDG_RUNTIME_DIR the state lives in a per-user 0700 dir."""
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    state_file = kb_view.state_file_for_root(tmp_path / "kb")
    assert state_file.parent == tmp_path / f"ai-knowledge-engine-viewer-{os.getuid()}"

    state_file.parent.mkdir(mode=0o755)
    state_file.parent.chmod(0o755)
    kb_view._write_state(
        state_file, url="http://127.0.0.1:1/", token="t", kb_root=tmp_path
    )
    assert stat.S_IMODE(state_file.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
    # TROUBLESHOOTING names the same folders.
    doc = (Path(kb_view.__file__).resolve().parents[2] / "docs" / "TROUBLESHOOTING.md")
    text = doc.read_text(encoding="utf-8")
    assert f"$XDG_RUNTIME_DIR/{kb_view._STATE_DIR_NAME}/" in text
    assert f"<temp dir>/{kb_view._STATE_DIR_NAME}-<uid>/" in text


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks and permission bits")
def test_planted_state_dir_is_not_trusted(
    tmp_path: Path, private_runtime: Path
) -> None:
    """MV18: a directory someone else prepared must not be read or written."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    state_file = kb_view.state_file_for_root(tmp_path)
    state_file.parent.symlink_to(elsewhere, target_is_directory=True)
    (elsewhere / state_file.name).write_text(
        json.dumps({"url": "http://evil/", "token": "x", "pid": 1, "kbRoot": "/"}),
        encoding="utf-8",
    )

    assert kb_view._read_state(state_file) is None
    with pytest.raises(OSError, match="not a private directory"):
        kb_view._write_state(
            state_file, url="http://127.0.0.1:1/", token="t", kb_root=tmp_path
        )


@pytest.mark.skipif(os.name == "nt", reason="the pre-0.16 folder is the current one on Windows")
def test_stop_reaches_a_viewer_started_by_an_older_engine(
    tmp_path: Path, private_runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MV18 upgrade path: a running pre-0.16 viewer is still found by --stop."""
    shared_tmp = tmp_path / "shared-tmp"
    shared_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(shared_tmp))
    _write_page(tmp_path, "domain/one.md", "# One\n")
    kb_root = tmp_path.resolve()
    server = kb_view.create_server(
        kb_root=kb_root,
        asset_dir=_viewer_assets(tmp_path),
        port=0,
        shutdown_token="old-token",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        legacy = kb_view._legacy_state_file(kb_root)
        assert legacy is not None and legacy.parent.parent == shared_tmp
        legacy.parent.mkdir(mode=0o755)
        host, port = server.server_address[:2]
        legacy.write_text(
            json.dumps(
                {
                    "url": f"http://{host}:{port}/",
                    "token": "old-token",
                    "pid": os.getpid(),
                    "kbRoot": str(kb_root),
                }
            ),
            encoding="utf-8",
        )
        # --background never reuses the old (unhardened) server.
        assert kb_view._running_state(kb_root) is None
        assert kb_view._print_status(kb_root) == 0
        assert kb_view._stop_background(kb_root) == 0
        thread.join(timeout=5)
        assert not thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()


class _Healthy:
    status = 200

    def __enter__(self) -> "_Healthy":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"ok": true}'


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_slow_health_check_keeps_the_viewer_state(
    tmp_path: Path, private_runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A busy viewer answering /api/health after 0.6 s is not gone: its state file
    was deleted, --stop then said "not running" and the server was orphaned."""
    state_file = kb_view.state_file_for_root(tmp_path)
    kb_view._write_state(state_file, url="http://127.0.0.1:9/", token="t0k", kb_root=tmp_path)
    timeouts: list[float] = []

    def slow_once(url: str, timeout: float) -> _Healthy:
        timeouts.append(timeout)
        if len(timeouts) == 1:
            raise TimeoutError("timed out")
        return _Healthy()

    monkeypatch.setattr(kb_view, "urlopen", slow_once)
    assert kb_view._running_state(tmp_path)["token"] == "t0k"
    assert timeouts[1] > timeouts[0]

    def silent(url: str, timeout: float) -> _Healthy:
        raise urllib.error.URLError(TimeoutError("timed out"))

    # No answer at all, but its process (this one) lives: still running.
    monkeypatch.setattr(kb_view, "urlopen", silent)
    assert kb_view._running_state(tmp_path)["token"] == "t0k"
    assert state_file.is_file()

    def refused(url: str, timeout: float) -> _Healthy:
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(kb_view, "urlopen", refused)
    assert kb_view._running_state(tmp_path) is None
    assert not state_file.exists()


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("127.0.0.1:8123", True),
        ("localhost:8123", True),
        ("LOCALHOST:8123", True),
        ("[::1]:8123", True),
        ("192.168.1.20:8123", True),  # --host 0.0.0.0 reached over the LAN
        ("127.0.0.1.nip.io:8123", False),  # a name that resolves to loopback
        ("attacker.example:8123", False),
        ("localhost.:8123", False),
        ("user@localhost:8123", False),
        ("localhost:8124", False),
        ("localhost", False),
        ("localhost:port", False),
        ("", False),
        (None, False),
    ],
)
def test_host_allowlist(host: str | None, allowed: bool) -> None:
    """MV11: only loopback names and IP literals on the viewer's own port."""
    assert kb_view._host_allowed(host, 8123) is allowed
    assert kb_view._host_allowed("localhost", 80) is True
