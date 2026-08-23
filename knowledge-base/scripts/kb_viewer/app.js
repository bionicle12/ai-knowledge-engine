(() => {
  "use strict";

  const palette = [
    "#6f8fb5",
    "#72a875",
    "#be963e",
    "#8177b7",
    "#4d9ba8",
    "#b66f7d",
    "#80919c",
    "#a77d56",
    "#6984a5",
    "#7d9e68",
  ];

  const STALE_MS = 180 * 24 * 60 * 60 * 1000;
  const HEALTH_COLORS = {
    orphans: "#e4a72f",
    broken: "#ef665f",
    stale: "#b48ce8",
    ambiguous: "#4fb3c6",
  };
  const HEALTH_ORDER = ["broken", "orphans", "stale", "ambiguous"];
  const PATH_COLOR = "#67e0b2";
  const FIX_QUEUE_LIMIT = 40;
  const CLUSTER_MIN_PAGES = 200;
  const CLUSTER_SCALE = 0.42;
  const CLUSTER_PREFIX = "cluster::";
  const WIKILINK_RE = /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g;

  const state = {
    graph: null,
    nodesById: new Map(),
    nodeData: null,
    edgeData: null,
    network: null,
    selectedId: null,
    selectedFolder: null,
    selectedTag: null,
    lifecycles: new Set(),
    health: new Set(),
    focus: false,
    focusDepth: 1,
    pathMode: false,
    pathFrom: null,
    path: null,
    history: [],
    historyIndex: -1,
    historyNavigating: false,
    clustered: false,
    groupColors: new Map(),
    exactIndex: new Map(),
    slugIndex: new Map(),
    adjacency: new Map(),
    edgeIdByPair: new Map(),
    edgeContextByPair: new Map(),
    staleIds: new Set(),
    brokenSources: new Set(),
    ambiguousSources: new Set(),
    prMax: 0,
    restoringHash: false,
    hashApplied: false,
    searchTimer: null,
    searchSeq: 0,
    toastTimer: null,
  };

  const el = {};

  document.addEventListener("DOMContentLoaded", () => {
    cacheElements();
    bindControls();
    loadGraph().catch(showFatalError);
  });

  function cacheElements() {
    [
      "app",
      "sidebar-toggle",
      "sidebar",
      "search-input",
      "search-results",
      "back-button",
      "forward-button",
      "fit-button",
      "focus-button",
      "depth-picker",
      "path-button",
      "refresh-button",
      "stat-pages",
      "stat-links",
      "health-chips",
      "count-orphans",
      "count-broken",
      "count-stale",
      "count-ambiguous",
      "clear-health",
      "fix-queue",
      "folder-filters",
      "tag-filters",
      "lifecycle-filters",
      "clear-folder",
      "clear-tag",
      "clear-all-filters",
      "full-graph-button",
      "selection-crumb",
      "path-banner",
      "path-steps",
      "path-close",
      "graph",
      "canvas-empty",
      "graph-legend",
      "canvas-status",
      "inspector",
      "inspector-empty",
      "inspector-content",
      "inspector-close",
      "resize-handle",
      "page-title",
      "page-path",
      "markdown-preview",
      "metadata-list",
      "inbound-count",
      "inbound-list",
      "outbound-count",
      "outbound-list",
      "open-file-button",
      "toast",
    ].forEach((id) => {
      el[id] = document.getElementById(id);
    });
  }

  function bindControls() {
    el["sidebar-toggle"].addEventListener("click", () => {
      const open = document.body.classList.toggle("sidebar-open");
      el["sidebar-toggle"].setAttribute("aria-pressed", String(open));
    });
    el["inspector-close"].addEventListener("click", () => {
      document.body.classList.remove("inspector-open");
    });
    el["back-button"].addEventListener("click", () => goHistory(-1));
    el["forward-button"].addEventListener("click", () => goHistory(1));
    el["fit-button"].addEventListener("click", fitGraph);
    el["focus-button"].addEventListener("click", () => {
      if (!state.selectedId) return;
      setFocus(!state.focus);
    });
    el["depth-picker"].addEventListener("click", (event) => {
      const button = event.target.closest("[data-depth]");
      if (!button) return;
      state.focusDepth = Number(button.dataset.depth);
      syncDepthPicker();
      if (state.focus) {
        applyGraphState();
        focusSelected();
      }
    });
    el["path-button"].addEventListener("click", togglePathMode);
    el["path-close"].addEventListener("click", clearPath);
    el["refresh-button"].addEventListener("click", refreshGraph);
    el["full-graph-button"].addEventListener("click", clearFocus);
    el["health-chips"].addEventListener("click", (event) => {
      const chip = event.target.closest("[data-health]");
      if (!chip) return;
      toggleHealth(chip.dataset.health);
    });
    el["clear-health"].addEventListener("click", () => {
      state.health.clear();
      syncHealthControls();
      renderFixQueue();
      applyGraphState();
    });
    el["clear-folder"].addEventListener("click", () => {
      state.selectedFolder = null;
      syncFilterControls();
      applyGraphState();
    });
    el["clear-tag"].addEventListener("click", () => {
      state.selectedTag = null;
      syncFilterControls();
      applyGraphState();
    });
    el["clear-all-filters"].addEventListener("click", clearAllFilters);
    el["search-input"].addEventListener("input", scheduleSearch);
    el["search-input"].addEventListener("keydown", handleSearchKeys);
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".search")) {
        el["search-results"].hidden = true;
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        el["search-results"].hidden = true;
        document.body.classList.remove("sidebar-open");
        if (state.pathMode || state.path) clearPath();
        else if (state.focus) clearFocus();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        el["search-input"].focus();
      }
      if (event.altKey && event.key === "ArrowLeft") {
        event.preventDefault();
        goHistory(-1);
      }
      if (event.altKey && event.key === "ArrowRight") {
        event.preventDefault();
        goHistory(1);
      }
    });
    el["open-file-button"].addEventListener("click", () => {
      if (state.selectedId) openSourceFile(state.selectedId, el["open-file-button"]);
    });
    setupInspectorResize();
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      cache: "no-store",
      ...options,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    if (!response.ok) {
      throw new Error(payload?.error || `Request failed (${response.status})`);
    }
    return payload;
  }

  async function loadGraph(graphPayload = null) {
    if (!window.vis?.Network || !window.vis?.DataSet) {
      throw new Error("The local graph renderer could not be loaded.");
    }
    const graph = graphPayload || (await request("/api/graph"));
    state.graph = graph;
    state.nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
    assignGroupColors(graph.nodes);
    buildIndexes(graph);
    state.lifecycles = new Set(
      graph.nodes.map((node) => node.lifecycle || "evolving")
    );
    if (state.path) {
      if (state.path.ids.every((id) => state.nodesById.has(id))) {
        state.path.edgeIds = pathEdgeIds(state.path.ids);
      } else {
        state.path = null;
        state.pathFrom = null;
        renderPathBanner();
      }
    }
    renderStats();
    renderFilters();
    renderLegend();
    createOrUpdateNetwork();
    renderFixQueue();
    setStatus(`${graph.stats.pages} pages · ${graph.stats.links} links`);
    if (!state.hashApplied) {
      state.hashApplied = true;
      await applyHashFromUrl();
    }
  }

  function assignGroupColors(nodes) {
    state.groupColors.clear();
    const groups = [...new Set(nodes.map((node) => node.group))].sort();
    groups.forEach((group, index) => {
      state.groupColors.set(group, palette[index % palette.length]);
    });
  }

  function buildIndexes(graph) {
    state.exactIndex = new Map(
      graph.nodes.map((node) => [node.id.toLowerCase(), node.id])
    );
    state.slugIndex = new Map();
    state.adjacency = new Map();
    graph.nodes.forEach((node) => {
      const slug = node.id.split("/").pop().toLowerCase();
      if (!state.slugIndex.has(slug)) state.slugIndex.set(slug, []);
      state.slugIndex.get(slug).push(node.id);
      state.adjacency.set(
        node.id,
        new Set([...node.inbound, ...node.outbound])
      );
    });
    state.slugIndex.forEach((ids) => ids.sort());
    state.edgeIdByPair = new Map();
    state.edgeContextByPair = new Map();
    graph.edges.forEach((edge) => {
      const key = `${edge.from}::${edge.to}`;
      if (!state.edgeIdByPair.has(key)) state.edgeIdByPair.set(key, edge.id);
      if (edge.context && !state.edgeContextByPair.has(key)) {
        state.edgeContextByPair.set(key, edge.context);
      }
    });
    state.prMax = Math.max(
      0,
      ...graph.nodes.map((node) => Number(node.pagerank) || 0)
    );
    state.staleIds = new Set(
      graph.nodes.filter(isStale).map((node) => node.id)
    );
    state.brokenSources = new Set(
      graph.diagnostics.broken.map((item) => item.source)
    );
    state.ambiguousSources = new Set(
      graph.diagnostics.ambiguous.map((item) => item.source)
    );
  }

  function isStale(node) {
    if (!node.lastVerified) return true;
    const timestamp = Date.parse(node.lastVerified);
    if (Number.isNaN(timestamp)) return true;
    return Date.now() - timestamp > STALE_MS;
  }

  function renderStats() {
    const { stats } = state.graph;
    el["stat-pages"].textContent = String(stats.pages);
    el["stat-links"].textContent = String(stats.links);
    el["count-orphans"].textContent = String(stats.orphans);
    el["count-broken"].textContent = String(stats.broken);
    el["count-stale"].textContent = String(state.staleIds.size);
    el["count-ambiguous"].textContent = String(stats.ambiguous);
  }

  function renderFilters() {
    renderFolderFilters();
    renderTagFilters();
    renderLifecycleFilters();
    syncFilterControls();
    syncHealthControls();
  }

  function renderFolderFilters() {
    const counts = new Map();
    state.graph.nodes.forEach((node) => {
      counts.set(node.group, (counts.get(node.group) || 0) + 1);
    });
    const fragment = document.createDocumentFragment();
    [...counts.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .forEach(([group, count]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "filter-item";
        button.dataset.group = group;
        button.setAttribute("aria-pressed", "false");

        const color = document.createElement("span");
        color.className = "folder-color";
        color.style.setProperty("--folder-color", state.groupColors.get(group));
        const label = document.createElement("span");
        label.textContent = group;
        const countNode = document.createElement("span");
        countNode.className = "filter-count";
        countNode.textContent = String(count);

        button.append(color, label, countNode);
        button.addEventListener("click", () => {
          state.selectedFolder = state.selectedFolder === group ? null : group;
          syncFilterControls();
          applyGraphState();
        });
        fragment.append(button);
      });
    el["folder-filters"].replaceChildren(fragment);
  }

  function renderTagFilters() {
    const counts = new Map();
    state.graph.nodes.forEach((node) => {
      node.tags.forEach((tag) => counts.set(tag, (counts.get(tag) || 0) + 1));
    });
    const fragment = document.createDocumentFragment();
    [...counts.entries()]
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .slice(0, 16)
      .forEach(([tag, count]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "tag-filter";
        button.dataset.tag = tag;
        button.setAttribute("aria-pressed", "false");
        button.textContent = `${tag} · ${count}`;
        button.addEventListener("click", () => {
          state.selectedTag = state.selectedTag === tag ? null : tag;
          syncFilterControls();
          applyGraphState();
        });
        fragment.append(button);
      });
    if (!fragment.childNodes.length) {
      const empty = document.createElement("span");
      empty.className = "neighbor-empty";
      empty.textContent = "No tags";
      fragment.append(empty);
    }
    el["tag-filters"].replaceChildren(fragment);
  }

  function renderLifecycleFilters() {
    const counts = new Map();
    state.graph.nodes.forEach((node) => {
      const lifecycle = node.lifecycle || "evolving";
      counts.set(lifecycle, (counts.get(lifecycle) || 0) + 1);
    });
    const fragment = document.createDocumentFragment();
    [...counts.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .forEach(([lifecycle, count]) => {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = lifecycle;
        input.checked = state.lifecycles.has(lifecycle);
        input.addEventListener("change", () => {
          if (input.checked) state.lifecycles.add(lifecycle);
          else state.lifecycles.delete(lifecycle);
          applyGraphState();
        });
        const text = document.createElement("span");
        text.textContent = lifecycle;
        const output = document.createElement("output");
        output.textContent = String(count);
        label.append(input, text, output);
        fragment.append(label);
      });
    el["lifecycle-filters"].replaceChildren(fragment);
  }

  function syncFilterControls() {
    el["folder-filters"].querySelectorAll("[data-group]").forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.group === state.selectedFolder)
      );
    });
    el["tag-filters"].querySelectorAll("[data-tag]").forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.tag === state.selectedTag)
      );
    });
  }

  function syncHealthControls() {
    el["health-chips"].querySelectorAll("[data-health]").forEach((chip) => {
      chip.setAttribute(
        "aria-pressed",
        String(state.health.has(chip.dataset.health))
      );
    });
    el["clear-health"].hidden = state.health.size === 0;
  }

  function toggleHealth(kind) {
    if (state.health.has(kind)) state.health.delete(kind);
    else state.health.add(kind);
    syncHealthControls();
    renderFixQueue();
    applyGraphState();
  }

  function renderFixQueue() {
    const container = el["fix-queue"];
    if (!state.graph || state.health.size === 0) {
      container.hidden = true;
      container.replaceChildren();
      return;
    }
    const fragment = document.createDocumentFragment();
    const groups = {
      orphans: () =>
        renderFixGroup(
          fragment,
          "orphans",
          "Orphan pages",
          state.graph.diagnostics.orphans.map((id) => ({
            nodeId: id,
            title: state.nodesById.get(id)?.label || id,
            context: state.nodesById.get(id)?.group || "",
          }))
        ),
      broken: () =>
        renderFixGroup(
          fragment,
          "broken",
          "Broken links",
          state.graph.diagnostics.broken.map((item) => ({
            nodeId: item.source,
            title: `${state.nodesById.get(item.source)?.label || item.source} → [[${item.target}]]`,
            context: item.context || "",
          }))
        ),
      stale: () =>
        renderFixGroup(
          fragment,
          "stale",
          "Stale pages",
          [...state.staleIds].sort().map((id) => {
            const node = state.nodesById.get(id);
            return {
              nodeId: id,
              title: node?.label || id,
              context: staleAge(node),
            };
          })
        ),
      ambiguous: () =>
        renderFixGroup(
          fragment,
          "ambiguous",
          "Ambiguous links",
          state.graph.diagnostics.ambiguous.map((item) => ({
            nodeId: item.source,
            title: `${state.nodesById.get(item.source)?.label || item.source} → [[${item.target}]]`,
            context: `matches: ${item.candidates.join(", ")}`,
          }))
        ),
    };
    ["orphans", "broken", "stale", "ambiguous"].forEach((kind) => {
      if (state.health.has(kind)) groups[kind]();
    });
    container.replaceChildren(fragment);
    container.hidden = false;
  }

  function staleAge(node) {
    if (!node?.lastVerified) return "never verified";
    const timestamp = Date.parse(node.lastVerified);
    if (Number.isNaN(timestamp)) return "never verified";
    const days = Math.floor((Date.now() - timestamp) / (24 * 60 * 60 * 1000));
    return `verified ${days} days ago`;
  }

  function renderFixGroup(fragment, kind, heading, items) {
    const group = document.createElement("div");
    group.className = "fix-group";
    const title = document.createElement("h3");
    const dot = document.createElement("span");
    dot.className = "chip-dot";
    dot.style.setProperty("--chip-color", HEALTH_COLORS[kind]);
    title.append(dot, `${heading} · ${items.length}`);
    group.append(title);
    items.slice(0, FIX_QUEUE_LIMIT).forEach((item) => {
      const row = document.createElement("div");
      row.className = "fix-item";
      const main = document.createElement("button");
      main.type = "button";
      main.className = "fix-item-main";
      const label = document.createElement("span");
      label.className = "fix-item-title";
      label.textContent = item.title;
      main.append(label);
      if (item.context) {
        const context = document.createElement("span");
        context.className = "fix-item-context";
        context.textContent = item.context;
        main.append(context);
      }
      main.addEventListener("click", () => selectNode(item.nodeId));
      const open = document.createElement("button");
      open.type = "button";
      open.className = "icon-button fix-item-open";
      open.title = "Open file";
      open.setAttribute("aria-label", "Open file");
      open.innerHTML =
        '<svg viewBox="0 0 24 24" aria-hidden="true">' +
        '<path d="M3 7h7l2 2h9v10H3z"></path><path d="M3 7V5h7l2 2"></path></svg>';
      open.addEventListener("click", (event) => {
        event.stopPropagation();
        openSourceFile(item.nodeId, open);
      });
      row.append(main, open);
      group.append(row);
    });
    if (items.length > FIX_QUEUE_LIMIT) {
      const more = document.createElement("div");
      more.className = "fix-more";
      more.textContent = `+${items.length - FIX_QUEUE_LIMIT} more`;
      group.append(more);
    }
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "fix-more";
      empty.textContent = "Nothing to fix";
      group.append(empty);
    }
    fragment.append(group);
  }

  function renderLegend() {
    const fragment = document.createDocumentFragment();
    [...state.groupColors.entries()].slice(0, 9).forEach(([group, color]) => {
      const item = document.createElement("span");
      item.className = "legend-item";
      const dot = document.createElement("span");
      dot.className = "legend-dot";
      dot.style.setProperty("--legend-color", color);
      const label = document.createElement("span");
      label.textContent = group;
      item.append(dot, label);
      fragment.append(item);
    });
    el["graph-legend"].replaceChildren(fragment);
  }

  function nodeSize(node, selected) {
    let magnitude;
    if (state.prMax > 0 && Number(node.pagerank) > 0) {
      magnitude = Math.sqrt(Number(node.pagerank) / state.prMax);
    } else {
      magnitude = Math.min(1, Math.sqrt(node.inDegree + node.outDegree) / 6);
    }
    const base = 7 + magnitude * 15;
    return selected ? Math.min(26, base + 4) : base;
  }

  function createOrUpdateNetwork() {
    const networkNodes = state.graph.nodes.map(toNetworkNode);
    const networkEdges = state.graph.edges.map((edge) => ({
      id: edge.id,
      from: edge.from,
      to: edge.to,
      arrows: { to: { enabled: true, scaleFactor: 0.35 } },
      color: {
        color: "rgba(136, 158, 175, 0.34)",
        highlight: "rgba(73, 167, 255, 0.78)",
        hover: "rgba(160, 185, 205, 0.6)",
      },
      width: 1,
      selectionWidth: 1.8,
      smooth: { enabled: true, type: "continuous", roundness: 0.18 },
    }));

    if (state.network) {
      openAllClusters();
      state.nodeData.clear();
      state.edgeData.clear();
      state.nodeData.add(networkNodes);
      state.edgeData.add(networkEdges);
      applyGraphState();
      fitGraph();
      return;
    }

    state.nodeData = new window.vis.DataSet(networkNodes);
    state.edgeData = new window.vis.DataSet(networkEdges);
    state.network = new window.vis.Network(
      el.graph,
      { nodes: state.nodeData, edges: state.edgeData },
      {
        autoResize: true,
        nodes: {
          shape: "dot",
          borderWidth: 1,
          chosen: false,
        },
        edges: {
          chosen: true,
          hoverWidth: 0.5,
        },
        interaction: {
          hover: true,
          keyboard: { enabled: true, bindToWindow: false },
          multiselect: false,
          tooltipDelay: 180,
          zoomView: true,
        },
        layout: {
          improvedLayout: true,
          clusterThreshold: 180,
        },
        physics: {
          enabled: true,
          solver: "barnesHut",
          barnesHut: {
            gravitationalConstant: -3200,
            centralGravity: 0.12,
            springLength: 105,
            springConstant: 0.035,
            damping: 0.22,
            avoidOverlap: 0.28,
          },
          stabilization: {
            enabled: true,
            iterations: 280,
            updateInterval: 25,
            fit: true,
          },
        },
      }
    );

    state.network.on("selectNode", ({ nodes }) => {
      if (!nodes.length) return;
      const nodeId = nodes[0];
      if (typeof nodeId === "string" && nodeId.startsWith(CLUSTER_PREFIX)) {
        state.network.openCluster(nodeId);
        return;
      }
      if (state.pathMode) {
        handlePathPick(nodeId);
        return;
      }
      selectNode(nodeId, { move: false });
    });
    state.network.on("deselectNode", () => {
      if (!state.focus && !state.pathMode) clearSelection();
    });
    state.network.on("doubleClick", ({ nodes }) => {
      if (!nodes.length) return;
      const nodeId = nodes[0];
      if (typeof nodeId === "string" && nodeId.startsWith(CLUSTER_PREFIX)) return;
      selectNode(nodeId, { move: false });
      setFocus(true);
    });
    state.network.on("stabilizationProgress", ({ iterations, total }) => {
      setStatus(`Laying out graph · ${Math.round((iterations / total) * 100)}%`);
    });
    state.network.once("stabilizationIterationsDone", () => {
      state.network.setOptions({ physics: false });
      setStatus(`${state.graph.stats.pages} pages · ${state.graph.stats.links} links`);
    });
    state.network.on("zoom", ({ scale }) => {
      updateLabelDensity(scale);
      maybeClusterFolders(scale);
    });
  }

  function toNetworkNode(node) {
    const color = state.groupColors.get(node.group) || palette[0];
    return {
      id: node.id,
      label: node.label,
      title: `${node.label}\n${node.path}`,
      shape: node.entryPoint ? "diamond" : "dot",
      size: nodeSize(node, false),
      color: {
        background: color,
        border: node.entryPoint ? "#8fb7d9" : "#17212a",
        highlight: { background: color, border: "#70bdff" },
        hover: { background: color, border: "#9acfff" },
      },
      borderWidth: node.entryPoint ? 2 : 1,
      font: {
        color: "#aebbc4",
        size: 11,
        face: 'Inter, "Segoe UI", sans-serif',
        strokeWidth: 3,
        strokeColor: "#0b1117",
      },
      groupName: node.group,
      baseColor: color,
    };
  }

  function updateLabelDensity(scale) {
    if (!state.nodeData || !state.graph || state.clustered) return;
    const updates = state.graph.nodes.map((node) => {
      const selected = node.id === state.selectedId;
      const important =
        node.inDegree + node.outDegree >= 4 || node.entryPoint;
      return {
        id: node.id,
        label: scale >= 0.62 || selected || important ? node.label : "",
      };
    });
    state.nodeData.update(updates);
  }

  function clusteringEligible() {
    return (
      state.graph &&
      state.graph.stats.pages >= CLUSTER_MIN_PAGES &&
      !state.selectedFolder &&
      !state.selectedTag &&
      state.health.size === 0 &&
      !state.focus &&
      !state.path &&
      !state.pathMode
    );
  }

  function maybeClusterFolders(scale) {
    if (!state.network) return;
    if (!state.clustered && scale < CLUSTER_SCALE && clusteringEligible()) {
      clusterFolders();
    } else if (state.clustered && scale >= CLUSTER_SCALE) {
      openAllClusters();
    }
  }

  function clusterFolders() {
    state.clustered = true;
    [...state.groupColors.keys()].forEach((group) => {
      const members = state.graph.nodes.filter((node) => node.group === group);
      if (members.length < 2) return;
      state.network.cluster({
        joinCondition: (nodeOptions) => nodeOptions.groupName === group,
        clusterNodeProperties: {
          id: `${CLUSTER_PREFIX}${group}`,
          label: `${group} · ${members.length}`,
          shape: "dot",
          size: Math.min(46, 20 + Math.sqrt(members.length) * 3.4),
          color: {
            background: state.groupColors.get(group),
            border: "#8fb7d9",
          },
          borderWidth: 2,
          font: {
            color: "#dbe5ec",
            size: 14,
            face: 'Inter, "Segoe UI", sans-serif',
            strokeWidth: 4,
            strokeColor: "#0b1117",
          },
        },
      });
    });
  }

  function openAllClusters() {
    if (!state.network || !state.clustered) return;
    [...state.groupColors.keys()].forEach((group) => {
      const clusterId = `${CLUSTER_PREFIX}${group}`;
      if (state.network.isCluster(clusterId)) {
        state.network.openCluster(clusterId);
      }
    });
    state.clustered = false;
  }

  function neighborhood(rootId, depth) {
    const seen = new Set([rootId]);
    let frontier = [rootId];
    for (let hop = 0; hop < depth; hop += 1) {
      const next = [];
      frontier.forEach((id) => {
        (state.adjacency.get(id) || []).forEach((neighbor) => {
          if (!seen.has(neighbor)) {
            seen.add(neighbor);
            next.push(neighbor);
          }
        });
      });
      frontier = next;
    }
    return seen;
  }

  function nodePassesFilters(node, focusSet) {
    if (state.selectedFolder && node.group !== state.selectedFolder) return false;
    if (state.selectedTag && !node.tags.includes(state.selectedTag)) return false;
    if (!state.lifecycles.has(node.lifecycle || "evolving")) return false;
    if (focusSet && !focusSet.has(node.id)) return false;
    return true;
  }

  function healthKindForNode(node) {
    for (const kind of HEALTH_ORDER) {
      if (!state.health.has(kind)) continue;
      if (kind === "orphans" && node.orphan) return kind;
      if (kind === "broken" && state.brokenSources.has(node.id)) return kind;
      if (kind === "stale" && state.staleIds.has(node.id)) return kind;
      if (kind === "ambiguous" && state.ambiguousSources.has(node.id)) {
        return kind;
      }
    }
    return null;
  }

  function applyGraphState() {
    if (!state.graph || !state.nodeData || !state.edgeData) return;
    openAllClusters();
    const focusSet =
      state.focus && state.selectedId
        ? neighborhood(state.selectedId, state.focusDepth)
        : null;
    const pathIds = state.path ? new Set(state.path.ids) : null;
    const visible = new Set();
    const updates = state.graph.nodes.map((node) => {
      let shown = nodePassesFilters(node, focusSet);
      if (pathIds?.has(node.id)) shown = true;
      if (shown) visible.add(node.id);
      const selected = node.id === state.selectedId;
      return {
        id: node.id,
        hidden: !shown,
        size: nodeSize(node, selected),
        borderWidth: selected ? 3 : node.entryPoint ? 2 : 1,
        color: nodeColorForState(node, pathIds),
      };
    });
    state.nodeData.update(updates);

    const edgeUpdates = state.graph.edges.map((edge) => {
      const onPath = state.path?.edgeIds.has(edge.id) || false;
      const touchesSelection =
        state.selectedId &&
        (edge.from === state.selectedId || edge.to === state.selectedId);
      let color = "rgba(136, 158, 175, 0.34)";
      let width = 1;
      if (onPath) {
        color = PATH_COLOR;
        width = 2.6;
      } else if (state.path) {
        color = "rgba(136, 158, 175, 0.12)";
      } else if (touchesSelection) {
        color = "rgba(73, 167, 255, 0.75)";
        width = 2;
      }
      return {
        id: edge.id,
        hidden: (!visible.has(edge.from) || !visible.has(edge.to)) && !onPath,
        width,
        color: {
          color,
          highlight: "rgba(73, 167, 255, 0.85)",
          hover: "rgba(160, 185, 205, 0.6)",
        },
      };
    });
    state.edgeData.update(edgeUpdates);
    el["canvas-empty"].hidden = visible.size !== 0;
    if (!state.pathMode) {
      setStatus(
        `${visible.size} of ${state.graph.stats.pages} pages · ${state.graph.stats.links} links`
      );
    }
    updateHash();
  }

  function nodeColorForState(node, pathIds) {
    const base = state.groupColors.get(node.group) || palette[0];
    const selectedBorder = node.id === state.selectedId ? "#70bdff" : null;
    if (pathIds) {
      if (pathIds.has(node.id)) {
        return {
          background: base,
          border: selectedBorder || PATH_COLOR,
          highlight: { background: base, border: PATH_COLOR },
          hover: { background: base, border: PATH_COLOR },
        };
      }
      return dimmedColor(base);
    }
    if (state.health.size > 0) {
      const kind = healthKindForNode(node);
      if (kind) {
        const issueColor = HEALTH_COLORS[kind];
        return {
          background: issueColor,
          border: selectedBorder || issueColor,
          highlight: { background: issueColor, border: "#ffffff" },
          hover: { background: issueColor, border: "#ffffff" },
        };
      }
      return dimmedColor(base);
    }
    return {
      background: base,
      border:
        selectedBorder || (node.entryPoint ? "#8fb7d9" : "#17212a"),
      highlight: { background: base, border: "#70bdff" },
      hover: { background: base, border: "#9acfff" },
    };
  }

  function dimmedColor(base) {
    return {
      background: "rgba(86, 101, 113, 0.28)",
      border: "rgba(86, 101, 113, 0.35)",
      highlight: { background: base, border: "#70bdff" },
      hover: { background: base, border: "#9acfff" },
    };
  }

  // --- Search -------------------------------------------------------------

  function scheduleSearch() {
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(runSearch, 200);
  }

  async function runSearch() {
    if (!state.graph) return;
    const query = el["search-input"].value.trim();
    if (!query) {
      el["search-results"].hidden = true;
      state.searchSeq += 1;
      return;
    }
    const seq = ++state.searchSeq;
    let results;
    try {
      const payload = await request(
        `/api/search?q=${encodeURIComponent(query)}`
      );
      results = payload.results;
    } catch (_error) {
      results = localSearch(query);
    }
    if (seq !== state.searchSeq) return;
    renderSearchResults(query, results);
  }

  function localSearch(query) {
    const needle = query.toLocaleLowerCase();
    return state.graph.nodes
      .filter((node) =>
        `${node.label} ${node.id} ${node.tags.join(" ")}`
          .toLocaleLowerCase()
          .includes(needle)
      )
      .sort((left, right) => {
        const leftStarts = left.label.toLocaleLowerCase().startsWith(needle)
          ? 0
          : 1;
        const rightStarts = right.label.toLocaleLowerCase().startsWith(needle)
          ? 0
          : 1;
        return leftStarts - rightStarts || left.label.localeCompare(right.label);
      })
      .slice(0, 10)
      .map((node) => ({
        id: node.id,
        label: node.label,
        path: node.path,
        field: "title",
        snippet: "",
      }));
  }

  function renderSearchResults(query, results) {
    const fragment = document.createDocumentFragment();
    results.slice(0, 12).forEach((result, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-result";
      button.dataset.nodeId = result.id;
      button.setAttribute("aria-selected", String(index === 0));
      const title = document.createElement("strong");
      title.textContent = result.label;
      const path = document.createElement("span");
      path.textContent = result.path;
      button.append(title, path);
      if (result.snippet) {
        const snippet = document.createElement("span");
        snippet.className = "search-snippet";
        appendHighlighted(snippet, result.snippet, query);
        button.append(snippet);
      }
      button.addEventListener("click", () => {
        selectNode(result.id);
        el["search-results"].hidden = true;
        el["search-input"].value = "";
      });
      fragment.append(button);
    });
    if (!results.length) {
      const empty = document.createElement("div");
      empty.className = "search-no-results";
      empty.textContent = "No matching pages";
      fragment.append(empty);
    }
    el["search-results"].replaceChildren(fragment);
    el["search-results"].hidden = false;
  }

  function appendHighlighted(parent, text, query) {
    const lower = text.toLocaleLowerCase();
    const needle = query.toLocaleLowerCase();
    let index = 0;
    while (index < text.length) {
      const found = lower.indexOf(needle, index);
      if (found === -1 || !needle) {
        parent.append(text.slice(index));
        return;
      }
      if (found > index) parent.append(text.slice(index, found));
      const mark = document.createElement("mark");
      mark.textContent = text.slice(found, found + needle.length);
      parent.append(mark);
      index = found + needle.length;
    }
  }

  function handleSearchKeys(event) {
    if (event.key !== "Enter" || el["search-results"].hidden) return;
    const selected = el["search-results"].querySelector("[data-node-id]");
    if (selected) {
      event.preventDefault();
      selectNode(selected.dataset.nodeId);
      el["search-results"].hidden = true;
      el["search-input"].value = "";
    }
  }

  // --- Selection, focus, history -------------------------------------------

  async function selectNode(nodeId, { move = true, recordHistory = true } = {}) {
    const node = state.nodesById.get(nodeId);
    if (!node) return;
    if (recordHistory && !state.historyNavigating) pushHistory(nodeId);
    state.selectedId = nodeId;
    el["focus-button"].disabled = false;
    el["selection-crumb"].textContent = node.label;
    el["selection-crumb"].hidden = false;
    openAllClusters();
    state.network.selectNodes([nodeId]);
    if (move) {
      state.network.focus(nodeId, {
        scale: Math.max(0.78, state.network.getScale()),
        animation: { duration: 360, easingFunction: "easeInOutQuad" },
      });
    }
    applyGraphState();
    document.body.classList.add("inspector-open");
    await showInspector(node);
  }

  function pushHistory(nodeId) {
    if (state.history[state.historyIndex] === nodeId) return;
    state.history = state.history.slice(0, state.historyIndex + 1);
    state.history.push(nodeId);
    if (state.history.length > 100) state.history.shift();
    state.historyIndex = state.history.length - 1;
    syncHistoryButtons();
  }

  function goHistory(delta) {
    const index = state.historyIndex + delta;
    if (index < 0 || index >= state.history.length) return;
    state.historyIndex = index;
    syncHistoryButtons();
    state.historyNavigating = true;
    selectNode(state.history[index], { recordHistory: false }).finally(() => {
      state.historyNavigating = false;
    });
  }

  function syncHistoryButtons() {
    el["back-button"].disabled = state.historyIndex <= 0;
    el["forward-button"].disabled =
      state.historyIndex >= state.history.length - 1;
  }

  function setFocus(enabled) {
    state.focus = enabled;
    el["focus-button"].setAttribute("aria-pressed", String(enabled));
    el["depth-picker"].hidden = !enabled;
    syncDepthPicker();
    applyGraphState();
    if (enabled) focusSelected();
  }

  function syncDepthPicker() {
    el["depth-picker"].querySelectorAll("[data-depth]").forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(Number(button.dataset.depth) === state.focusDepth)
      );
    });
  }

  // --- Shortest path --------------------------------------------------------

  function togglePathMode() {
    if (state.pathMode || state.path) {
      clearPath();
      return;
    }
    state.pathMode = true;
    state.pathFrom = state.selectedId;
    el["path-button"].setAttribute("aria-pressed", "true");
    setStatus(
      state.pathFrom
        ? `Path: from “${state.nodesById.get(state.pathFrom)?.label}” — pick the target page`
        : "Path: pick the first page"
    );
  }

  function handlePathPick(nodeId) {
    if (!state.pathFrom) {
      state.pathFrom = nodeId;
      setStatus(
        `Path: from “${state.nodesById.get(nodeId)?.label}” — pick the target page`
      );
      return;
    }
    if (nodeId === state.pathFrom) return;
    const ids = shortestPath(state.pathFrom, nodeId);
    if (!ids) {
      showToast("No path between these pages", true);
      return;
    }
    state.path = { ids, edgeIds: pathEdgeIds(ids) };
    state.pathMode = false;
    renderPathBanner();
    applyGraphState();
    state.network.fit({
      nodes: ids,
      animation: { duration: 420, easingFunction: "easeInOutQuad" },
    });
  }

  function shortestPath(from, to) {
    const previous = new Map([[from, null]]);
    const queue = [from];
    while (queue.length) {
      const current = queue.shift();
      if (current === to) break;
      for (const next of state.adjacency.get(current) || []) {
        if (!previous.has(next)) {
          previous.set(next, current);
          queue.push(next);
        }
      }
    }
    if (!previous.has(to)) return null;
    const ids = [];
    for (let cursor = to; cursor !== null; cursor = previous.get(cursor)) {
      ids.unshift(cursor);
    }
    return ids;
  }

  function pathEdgeIds(ids) {
    const edgeIds = new Set();
    for (let index = 0; index < ids.length - 1; index += 1) {
      const forward = state.edgeIdByPair.get(`${ids[index]}::${ids[index + 1]}`);
      const backward = state.edgeIdByPair.get(`${ids[index + 1]}::${ids[index]}`);
      if (forward) edgeIds.add(forward);
      else if (backward) edgeIds.add(backward);
    }
    return edgeIds;
  }

  function renderPathBanner() {
    if (!state.path) {
      el["path-banner"].hidden = true;
      el["path-steps"].replaceChildren();
      return;
    }
    const fragment = document.createDocumentFragment();
    state.path.ids.forEach((id, index) => {
      if (index > 0) {
        const arrow = document.createElement("span");
        arrow.className = "path-arrow";
        arrow.textContent = "→";
        fragment.append(arrow);
      }
      const step = document.createElement("button");
      step.type = "button";
      step.className = "path-step";
      step.textContent = state.nodesById.get(id)?.label || id;
      step.addEventListener("click", () => selectNode(id));
      fragment.append(step);
    });
    el["path-steps"].replaceChildren(fragment);
    el["path-banner"].hidden = false;
  }

  function clearPath() {
    state.pathMode = false;
    state.pathFrom = null;
    state.path = null;
    el["path-button"].setAttribute("aria-pressed", "false");
    renderPathBanner();
    applyGraphState();
  }

  // --- Inspector -------------------------------------------------------------

  async function showInspector(node) {
    el["inspector-empty"].hidden = true;
    el["inspector-content"].hidden = false;
    el["page-title"].textContent = node.label;
    el["page-path"].textContent = node.path;
    el["markdown-preview"].replaceChildren(
      Object.assign(document.createElement("p"), { textContent: "Loading…" })
    );
    renderNeighborList("inbound", node.inbound, node.id);
    renderNeighborList("outbound", node.outbound, node.id);
    try {
      const page = await request(`/api/page?id=${encodeURIComponent(node.id)}`);
      if (state.selectedId !== node.id) return;
      el["page-title"].textContent = page.label;
      el["page-path"].textContent = page.path;
      renderMarkdown(el["markdown-preview"], page.markdown);
      renderMetadata(page.metadata);
    } catch (error) {
      if (state.selectedId === node.id) {
        el["markdown-preview"].replaceChildren(
          Object.assign(document.createElement("p"), {
            textContent: `Cannot load page: ${error.message}`,
          })
        );
      }
    }
  }

  function renderMetadata(metadata) {
    const priority = [
      "source",
      "lifecycle",
      "importance",
      "confidence",
      "last_verified",
      "extracted_at",
      "tags",
    ];
    const entries = Object.entries(metadata || {}).sort(([left], [right]) => {
      const leftIndex = priority.indexOf(left);
      const rightIndex = priority.indexOf(right);
      if (leftIndex >= 0 || rightIndex >= 0) {
        return (
          (leftIndex >= 0 ? leftIndex : priority.length) -
          (rightIndex >= 0 ? rightIndex : priority.length)
        );
      }
      return left.localeCompare(right);
    });
    const fragment = document.createDocumentFragment();
    entries.forEach(([key, value]) => {
      const row = document.createElement("div");
      row.className = "metadata-row";
      const term = document.createElement("dt");
      term.textContent = key.replaceAll("_", " ");
      const description = document.createElement("dd");
      description.textContent =
        typeof value === "object" ? JSON.stringify(value) : String(value);
      row.append(term, description);
      fragment.append(row);
    });
    if (!entries.length) {
      const empty = document.createElement("div");
      empty.className = "neighbor-empty";
      empty.textContent = "No frontmatter";
      fragment.append(empty);
    }
    el["metadata-list"].replaceChildren(fragment);
  }

  function renderNeighborList(direction, ids, currentId) {
    const list = el[`${direction}-list`];
    el[`${direction}-count`].textContent = `(${ids.length})`;
    const fragment = document.createDocumentFragment();
    ids.forEach((id) => {
      const node = state.nodesById.get(id);
      if (!node) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "neighbor-button";
      const head = document.createElement("span");
      head.className = "neighbor-head";
      const label = document.createElement("span");
      label.textContent = node.label;
      const group = document.createElement("span");
      group.textContent = node.group;
      head.append(label, group);
      button.append(head);
      const context =
        direction === "inbound"
          ? state.edgeContextByPair.get(`${id}::${currentId}`)
          : state.edgeContextByPair.get(`${currentId}::${id}`);
      if (context) {
        const line = document.createElement("span");
        line.className = "neighbor-context";
        line.textContent = context;
        button.append(line);
      }
      button.addEventListener("click", () => selectNode(id));
      fragment.append(button);
    });
    if (!fragment.childNodes.length) {
      const empty = document.createElement("span");
      empty.className = "neighbor-empty";
      empty.textContent = "No links";
      fragment.append(empty);
    }
    list.replaceChildren(fragment);
  }

  // --- Markdown preview with clickable wikilinks -----------------------------

  function resolveWikilink(raw) {
    let value = String(raw).trim().replace(/\\/g, "/");
    const anchorIndex = value.indexOf("#");
    if (anchorIndex >= 0) value = value.slice(0, anchorIndex).trim();
    if (/^knowledge\//i.test(value)) value = value.slice("knowledge/".length);
    if (/\.md$/i.test(value)) value = value.slice(0, -3);
    while (value.startsWith("./")) value = value.slice(2);
    value = value.replace(/^\/+|\/+$/g, "");
    const lower = value.toLowerCase();
    if (!lower) return {};
    if (lower.includes("/")) {
      const id = state.exactIndex.get(lower);
      return id ? { id } : {};
    }
    const candidates = state.slugIndex.get(lower) || [];
    if (candidates.length === 1) return { id: candidates[0] };
    if (candidates.length > 1) return { candidates };
    return {};
  }

  function wikilinkElement(target, alias) {
    const resolved = resolveWikilink(target);
    const text = alias || target;
    if (resolved.id) {
      const link = document.createElement("a");
      link.className = "wikilink";
      link.textContent = text;
      link.href = `#sel=${encodeURIComponent(resolved.id)}`;
      link.title = resolved.id;
      link.addEventListener("click", (event) => {
        event.preventDefault();
        selectNode(resolved.id);
      });
      return link;
    }
    const span = document.createElement("span");
    span.textContent = text;
    if (resolved.candidates) {
      span.className = "wikilink wikilink-ambiguous";
      span.title = `Ambiguous: ${resolved.candidates.join(", ")}`;
    } else {
      span.className = "wikilink wikilink-broken";
      span.title = "No page with this name";
    }
    return span;
  }

  function appendInline(parent, text) {
    let last = 0;
    for (const match of text.matchAll(WIKILINK_RE)) {
      if (match.index > last) parent.append(text.slice(last, match.index));
      parent.append(wikilinkElement(match[1], match[2]));
      last = match.index + match[0].length;
    }
    if (last < text.length) parent.append(text.slice(last));
  }

  function renderMarkdown(container, markdown) {
    const fragment = document.createDocumentFragment();
    const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
    let paragraph = [];
    let list = null;
    let code = null;

    const flushParagraph = () => {
      if (!paragraph.length) return;
      const p = document.createElement("p");
      appendInline(p, paragraph.join(" "));
      fragment.append(p);
      paragraph = [];
    };
    const flushList = () => {
      if (!list) return;
      fragment.append(list);
      list = null;
    };

    lines.forEach((line) => {
      if (line.startsWith("```")) {
        flushParagraph();
        flushList();
        if (code) {
          fragment.append(code);
          code = null;
        } else {
          code = document.createElement("pre");
        }
        return;
      }
      if (code) {
        code.textContent += `${code.textContent ? "\n" : ""}${line}`;
        return;
      }
      const heading = /^(#{1,4})\s+(.+)$/.exec(line);
      if (heading) {
        flushParagraph();
        flushList();
        const h = document.createElement(`h${heading[1].length}`);
        h.textContent = heading[2];
        fragment.append(h);
        return;
      }
      const bullet = /^\s*[-*]\s+(.+)$/.exec(line);
      if (bullet) {
        flushParagraph();
        if (!list || list.tagName !== "UL") list = document.createElement("ul");
        const item = document.createElement("li");
        appendInline(item, bullet[1]);
        list.append(item);
        return;
      }
      const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
      if (ordered) {
        flushParagraph();
        if (!list || list.tagName !== "OL") list = document.createElement("ol");
        const item = document.createElement("li");
        appendInline(item, ordered[1]);
        list.append(item);
        return;
      }
      const quote = /^>\s?(.*)$/.exec(line);
      if (quote) {
        flushParagraph();
        flushList();
        const blockquote = document.createElement("blockquote");
        appendInline(blockquote, quote[1]);
        fragment.append(blockquote);
        return;
      }
      if (!line.trim()) {
        flushParagraph();
        flushList();
        return;
      }
      paragraph.push(line.trim());
    });
    flushParagraph();
    flushList();
    if (code) fragment.append(code);
    container.replaceChildren(fragment);
  }

  // --- URL hash state ---------------------------------------------------------

  function updateHash() {
    if (state.restoringHash) return;
    const params = new URLSearchParams();
    if (state.selectedId) params.set("sel", state.selectedId);
    if (state.focus) params.set("focus", String(state.focusDepth));
    if (state.health.size) params.set("health", [...state.health].join(","));
    if (state.selectedFolder) params.set("folder", state.selectedFolder);
    if (state.selectedTag) params.set("tag", state.selectedTag);
    if (state.path) {
      params.set(
        "path",
        `${state.path.ids[0]}~${state.path.ids[state.path.ids.length - 1]}`
      );
    }
    const hash = params.toString();
    window.history.replaceState(
      null,
      "",
      hash
        ? `#${hash}`
        : window.location.pathname + window.location.search
    );
  }

  async function applyHashFromUrl() {
    const raw = window.location.hash.replace(/^#/, "");
    if (!raw) return;
    const params = new URLSearchParams(raw);
    state.restoringHash = true;
    try {
      const folder = params.get("folder");
      if (folder && state.groupColors.has(folder)) {
        state.selectedFolder = folder;
      }
      const tag = params.get("tag");
      if (tag) state.selectedTag = tag;
      const health = params.get("health");
      if (health) {
        health
          .split(",")
          .filter((kind) => kind in HEALTH_COLORS)
          .forEach((kind) => state.health.add(kind));
      }
      syncFilterControls();
      syncHealthControls();
      renderFixQueue();
      const selected = params.get("sel");
      if (selected && state.nodesById.has(selected)) {
        await selectNode(selected);
        const focusDepth = Number(params.get("focus"));
        if (focusDepth >= 1 && focusDepth <= 3) {
          state.focusDepth = focusDepth;
          setFocus(true);
        }
      }
      const path = params.get("path");
      if (path) {
        const [from, to] = path.split("~");
        if (state.nodesById.has(from) && state.nodesById.has(to)) {
          const ids = shortestPath(from, to);
          if (ids) {
            state.path = { ids, edgeIds: pathEdgeIds(ids) };
            renderPathBanner();
          }
        }
      }
      applyGraphState();
    } finally {
      state.restoringHash = false;
      updateHash();
    }
  }

  // --- Misc actions ------------------------------------------------------------

  function clearSelection() {
    state.selectedId = null;
    state.focus = false;
    el["focus-button"].disabled = true;
    el["focus-button"].setAttribute("aria-pressed", "false");
    el["depth-picker"].hidden = true;
    el["selection-crumb"].hidden = true;
    el["inspector-content"].hidden = true;
    el["inspector-empty"].hidden = false;
    document.body.classList.remove("inspector-open");
    applyGraphState();
  }

  function clearFocus() {
    state.focus = false;
    el["focus-button"].setAttribute("aria-pressed", "false");
    el["depth-picker"].hidden = true;
    applyGraphState();
    fitGraph();
  }

  function focusSelected() {
    if (!state.selectedId) return;
    state.network.fit({
      nodes: [...neighborhood(state.selectedId, state.focusDepth)],
      animation: { duration: 420, easingFunction: "easeInOutQuad" },
    });
  }

  function clearAllFilters() {
    state.selectedFolder = null;
    state.selectedTag = null;
    state.lifecycles = new Set(
      state.graph.nodes.map((node) => node.lifecycle || "evolving")
    );
    state.health.clear();
    state.focus = false;
    state.pathMode = false;
    state.path = null;
    state.pathFrom = null;
    renderLifecycleFilters();
    syncFilterControls();
    syncHealthControls();
    renderFixQueue();
    renderPathBanner();
    el["focus-button"].setAttribute("aria-pressed", "false");
    el["depth-picker"].hidden = true;
    el["path-button"].setAttribute("aria-pressed", "false");
    applyGraphState();
    fitGraph();
  }

  function fitGraph() {
    if (!state.network) return;
    state.network.fit({
      animation: { duration: 360, easingFunction: "easeInOutQuad" },
    });
  }

  async function refreshGraph() {
    el["refresh-button"].disabled = true;
    setStatus("Refreshing knowledge…");
    try {
      const selected = state.selectedId;
      const graph = await request("/api/refresh", { method: "POST" });
      await loadGraph(graph);
      if (selected && state.nodesById.has(selected)) await selectNode(selected);
      else if (selected) clearSelection();
      showToast("Knowledge graph refreshed");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      el["refresh-button"].disabled = false;
    }
  }

  async function openSourceFile(nodeId, button) {
    if (button) button.disabled = true;
    try {
      await request(`/api/open?id=${encodeURIComponent(nodeId)}`, {
        method: "POST",
        headers: { "X-KB-Viewer": "1" },
      });
      showToast("Opened in the default Markdown application");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function setupInspectorResize() {
    let startX = 0;
    let startWidth = 0;
    const onMove = (event) => {
      const width = Math.min(
        Math.max(320, startWidth + (startX - event.clientX)),
        Math.min(window.innerWidth * 0.56, 680)
      );
      document.documentElement.style.setProperty("--inspector-width", `${width}px`);
    };
    const onUp = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    el["resize-handle"].addEventListener("pointerdown", (event) => {
      if (window.innerWidth <= 820) return;
      startX = event.clientX;
      startWidth = el.inspector.getBoundingClientRect().width;
      document.body.style.cursor = "ew-resize";
      document.body.style.userSelect = "none";
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
    });
  }

  function setStatus(message) {
    el["canvas-status"].textContent = message;
  }

  function showToast(message, isError = false) {
    clearTimeout(state.toastTimer);
    el.toast.textContent = message;
    el.toast.classList.toggle("error", isError);
    el.toast.hidden = false;
    state.toastTimer = setTimeout(() => {
      el.toast.hidden = true;
    }, 3200);
  }

  function showFatalError(error) {
    setStatus("Viewer failed to load");
    el["canvas-empty"].hidden = false;
    el["canvas-empty"].querySelector("strong").textContent = error.message;
    el["clear-all-filters"].hidden = true;
    showToast(error.message, true);
  }
})();
