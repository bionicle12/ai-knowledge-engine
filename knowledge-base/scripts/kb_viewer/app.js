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
    lens: "none",
    focus: false,
    groupColors: new Map(),
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
      "fit-button",
      "focus-button",
      "refresh-button",
      "stat-pages",
      "stat-links",
      "stat-orphans",
      "stat-broken",
      "folder-filters",
      "tag-filters",
      "lifecycle-filters",
      "quality-filters",
      "lens-orphans",
      "lens-broken",
      "clear-folder",
      "clear-tag",
      "clear-all-filters",
      "full-graph-button",
      "selection-crumb",
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
    el["fit-button"].addEventListener("click", fitGraph);
    el["focus-button"].addEventListener("click", () => {
      if (!state.selectedId) return;
      state.focus = !state.focus;
      el["focus-button"].setAttribute("aria-pressed", String(state.focus));
      applyGraphState();
      if (state.focus) focusSelected();
    });
    el["refresh-button"].addEventListener("click", refreshGraph);
    el["full-graph-button"].addEventListener("click", clearFocus);
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
    el["quality-filters"].addEventListener("change", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      state.lens = target.value;
      applyGraphState();
    });
    el["search-input"].addEventListener("input", renderSearchResults);
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
        if (state.focus) clearFocus();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        el["search-input"].focus();
      }
    });
    el["open-file-button"].addEventListener("click", openSelectedFile);
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
    state.lifecycles = new Set(
      graph.nodes.map((node) => node.lifecycle || "evolving")
    );
    renderStats();
    renderFilters();
    renderLegend();
    createOrUpdateNetwork();
    setStatus(`${graph.stats.pages} pages · ${graph.stats.links} links`);
  }

  function assignGroupColors(nodes) {
    state.groupColors.clear();
    const groups = [...new Set(nodes.map((node) => node.group))].sort();
    groups.forEach((group, index) => {
      state.groupColors.set(group, palette[index % palette.length]);
    });
  }

  function renderStats() {
    const { stats } = state.graph;
    el["stat-pages"].textContent = String(stats.pages);
    el["stat-links"].textContent = String(stats.links);
    el["stat-orphans"].textContent = String(stats.orphans);
    el["stat-broken"].textContent = String(stats.broken);
    el["lens-orphans"].textContent = String(stats.orphans);
    el["lens-broken"].textContent = String(stats.broken);
  }

  function renderFilters() {
    renderFolderFilters();
    renderTagFilters();
    renderLifecycleFilters();
    syncFilterControls();
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

  function createOrUpdateNetwork() {
    const networkNodes = state.graph.nodes.map(toNetworkNode);
    const networkEdges = state.graph.edges.map((edge) => ({
      id: edge.id,
      from: edge.from,
      to: edge.to,
      arrows: { to: { enabled: true, scaleFactor: 0.35 } },
      color: {
        color: "rgba(118, 139, 153, 0.22)",
        highlight: "rgba(73, 167, 255, 0.72)",
        hover: "rgba(148, 175, 193, 0.5)",
      },
      width: 0.8,
      selectionWidth: 1.8,
      smooth: { enabled: true, type: "continuous", roundness: 0.18 },
    }));

    if (state.network) {
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
      if (nodes.length) selectNode(nodes[0], { move: false });
    });
    state.network.on("deselectNode", () => {
      if (!state.focus) clearSelection();
    });
    state.network.on("doubleClick", ({ nodes }) => {
      if (!nodes.length) return;
      selectNode(nodes[0], { move: false });
      state.focus = true;
      el["focus-button"].setAttribute("aria-pressed", "true");
      applyGraphState();
      focusSelected();
    });
    state.network.on("stabilizationProgress", ({ iterations, total }) => {
      setStatus(`Laying out graph · ${Math.round((iterations / total) * 100)}%`);
    });
    state.network.once("stabilizationIterationsDone", () => {
      state.network.setOptions({ physics: false });
      setStatus(`${state.graph.stats.pages} pages · ${state.graph.stats.links} links`);
    });
    state.network.on("zoom", ({ scale }) => updateLabelDensity(scale));
  }

  function toNetworkNode(node) {
    const color = state.groupColors.get(node.group) || palette[0];
    const degree = node.inDegree + node.outDegree;
    return {
      id: node.id,
      label: node.label,
      title: `${node.label}\n${node.path}`,
      size: Math.min(17, 8 + Math.sqrt(degree) * 2.2),
      color: {
        background: color,
        border: "#17212a",
        highlight: { background: color, border: "#70bdff" },
        hover: { background: color, border: "#9acfff" },
      },
      borderWidth: 1,
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
    if (!state.nodeData || !state.graph) return;
    const updates = state.graph.nodes.map((node) => {
      const selected = node.id === state.selectedId;
      const important = node.inDegree + node.outDegree >= 4;
      return {
        id: node.id,
        label: scale >= 0.62 || selected || important ? node.label : "",
      };
    });
    state.nodeData.update(updates);
  }

  function nodePassesFilters(node) {
    if (state.selectedFolder && node.group !== state.selectedFolder) return false;
    if (state.selectedTag && !node.tags.includes(state.selectedTag)) return false;
    if (!state.lifecycles.has(node.lifecycle || "evolving")) return false;
    if (state.focus && state.selectedId) {
      const selected = state.nodesById.get(state.selectedId);
      const neighborhood = new Set([
        state.selectedId,
        ...selected.inbound,
        ...selected.outbound,
      ]);
      if (!neighborhood.has(node.id)) return false;
    }
    return true;
  }

  function nodeMatchesLens(node) {
    if (state.lens === "none") return true;
    if (state.lens === "orphans") return node.orphan;
    if (state.lens === "broken") {
      return state.graph.diagnostics.broken.some((item) => item.source === node.id);
    }
    if (state.lens === "important") return Number(node.importance || 0) >= 8;
    if (state.lens === "stale") {
      if (!node.lastVerified) return true;
      const timestamp = Date.parse(node.lastVerified);
      if (Number.isNaN(timestamp)) return true;
      return Date.now() - timestamp > 180 * 24 * 60 * 60 * 1000;
    }
    return true;
  }

  function applyGraphState() {
    if (!state.graph || !state.nodeData || !state.edgeData) return;
    const visible = new Set();
    const updates = state.graph.nodes.map((node) => {
      const shown = nodePassesFilters(node);
      if (shown) visible.add(node.id);
      const selected = node.id === state.selectedId;
      const lensMatch = nodeMatchesLens(node);
      const color = nodeColorForState(node, lensMatch);
      return {
        id: node.id,
        hidden: !shown,
        size: selected
          ? Math.min(23, 14 + Math.sqrt(node.inDegree + node.outDegree) * 2.4)
          : Math.min(17, 8 + Math.sqrt(node.inDegree + node.outDegree) * 2.2),
        borderWidth: selected ? 3 : lensMatch && state.lens !== "none" ? 2 : 1,
        color,
      };
    });
    state.nodeData.update(updates);

    const edgeUpdates = state.graph.edges.map((edge) => {
      const touchesSelection =
        state.selectedId &&
        (edge.from === state.selectedId || edge.to === state.selectedId);
      return {
        id: edge.id,
        hidden: !visible.has(edge.from) || !visible.has(edge.to),
        width: touchesSelection ? 1.8 : 0.8,
        color: {
          color: touchesSelection
            ? "rgba(73, 167, 255, 0.7)"
            : "rgba(118, 139, 153, 0.22)",
          highlight: "rgba(73, 167, 255, 0.82)",
          hover: "rgba(148, 175, 193, 0.5)",
        },
      };
    });
    state.edgeData.update(edgeUpdates);
    el["canvas-empty"].hidden = visible.size !== 0;
    setStatus(
      `${visible.size} of ${state.graph.stats.pages} pages · ${state.graph.stats.links} links`
    );
  }

  function nodeColorForState(node, lensMatch) {
    const base = state.groupColors.get(node.group) || palette[0];
    if (state.lens === "none") {
      return {
        background: base,
        border: node.id === state.selectedId ? "#70bdff" : "#17212a",
        highlight: { background: base, border: "#70bdff" },
        hover: { background: base, border: "#9acfff" },
      };
    }
    if (lensMatch) {
      const issueColor = state.lens === "broken" ? "#e4a72f" : "#66b7f2";
      return {
        background: issueColor,
        border: node.id === state.selectedId ? "#d5ecff" : issueColor,
        highlight: { background: issueColor, border: "#ffffff" },
        hover: { background: issueColor, border: "#ffffff" },
      };
    }
    return {
      background: "rgba(86, 101, 113, 0.28)",
      border: "rgba(86, 101, 113, 0.35)",
      highlight: { background: base, border: "#70bdff" },
      hover: { background: base, border: "#9acfff" },
    };
  }

  function renderSearchResults() {
    if (!state.graph) return;
    const query = el["search-input"].value.trim().toLocaleLowerCase();
    if (!query) {
      el["search-results"].hidden = true;
      return;
    }
    const matches = state.graph.nodes
      .filter((node) =>
        `${node.label} ${node.id} ${node.tags.join(" ")}`
          .toLocaleLowerCase()
          .includes(query)
      )
      .sort((left, right) => {
        const leftStarts = left.label.toLocaleLowerCase().startsWith(query) ? 0 : 1;
        const rightStarts = right.label.toLocaleLowerCase().startsWith(query) ? 0 : 1;
        return leftStarts - rightStarts || left.label.localeCompare(right.label);
      })
      .slice(0, 10);

    const fragment = document.createDocumentFragment();
    matches.forEach((node, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-result";
      button.dataset.nodeId = node.id;
      button.setAttribute("aria-selected", String(index === 0));
      const title = document.createElement("strong");
      title.textContent = node.label;
      const path = document.createElement("span");
      path.textContent = node.path;
      button.append(title, path);
      button.addEventListener("click", () => {
        selectNode(node.id);
        el["search-results"].hidden = true;
        el["search-input"].value = "";
      });
      fragment.append(button);
    });
    if (!matches.length) {
      const empty = document.createElement("div");
      empty.className = "search-no-results";
      empty.textContent = "No matching pages";
      fragment.append(empty);
    }
    el["search-results"].replaceChildren(fragment);
    el["search-results"].hidden = false;
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

  async function selectNode(nodeId, { move = true } = {}) {
    const node = state.nodesById.get(nodeId);
    if (!node) return;
    state.selectedId = nodeId;
    el["focus-button"].disabled = false;
    el["selection-crumb"].textContent = node.label;
    el["selection-crumb"].hidden = false;
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

  async function showInspector(node) {
    el["inspector-empty"].hidden = true;
    el["inspector-content"].hidden = false;
    el["page-title"].textContent = node.label;
    el["page-path"].textContent = node.path;
    el["markdown-preview"].replaceChildren(
      Object.assign(document.createElement("p"), { textContent: "Loading…" })
    );
    renderNeighborList("inbound", node.inbound);
    renderNeighborList("outbound", node.outbound);
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

  function renderNeighborList(direction, ids) {
    const list = el[`${direction}-list`];
    el[`${direction}-count`].textContent = `(${ids.length})`;
    const fragment = document.createDocumentFragment();
    ids.forEach((id) => {
      const node = state.nodesById.get(id);
      if (!node) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "neighbor-button";
      const label = document.createElement("span");
      label.textContent = node.label;
      const group = document.createElement("span");
      group.textContent = node.group;
      button.append(label, group);
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

  function renderMarkdown(container, markdown) {
    const fragment = document.createDocumentFragment();
    const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
    let paragraph = [];
    let list = null;
    let code = null;

    const flushParagraph = () => {
      if (!paragraph.length) return;
      const p = document.createElement("p");
      p.textContent = paragraph.join(" ");
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
        item.textContent = bullet[1];
        list.append(item);
        return;
      }
      const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
      if (ordered) {
        flushParagraph();
        if (!list || list.tagName !== "OL") list = document.createElement("ol");
        const item = document.createElement("li");
        item.textContent = ordered[1];
        list.append(item);
        return;
      }
      const quote = /^>\s?(.*)$/.exec(line);
      if (quote) {
        flushParagraph();
        flushList();
        const blockquote = document.createElement("blockquote");
        blockquote.textContent = quote[1];
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

  function clearSelection() {
    state.selectedId = null;
    state.focus = false;
    el["focus-button"].disabled = true;
    el["focus-button"].setAttribute("aria-pressed", "false");
    el["selection-crumb"].hidden = true;
    el["inspector-content"].hidden = true;
    el["inspector-empty"].hidden = false;
    document.body.classList.remove("inspector-open");
    applyGraphState();
  }

  function clearFocus() {
    state.focus = false;
    el["focus-button"].setAttribute("aria-pressed", "false");
    applyGraphState();
    fitGraph();
  }

  function focusSelected() {
    if (!state.selectedId) return;
    state.network.fit({
      nodes: [
        state.selectedId,
        ...state.nodesById.get(state.selectedId).inbound,
        ...state.nodesById.get(state.selectedId).outbound,
      ],
      animation: { duration: 420, easingFunction: "easeInOutQuad" },
    });
  }

  function clearAllFilters() {
    state.selectedFolder = null;
    state.selectedTag = null;
    state.lifecycles = new Set(
      state.graph.nodes.map((node) => node.lifecycle || "evolving")
    );
    state.lens = "none";
    state.focus = false;
    const neutral = el["quality-filters"].querySelector('[value="none"]');
    if (neutral) neutral.checked = true;
    renderLifecycleFilters();
    syncFilterControls();
    el["focus-button"].setAttribute("aria-pressed", "false");
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

  async function openSelectedFile() {
    if (!state.selectedId) return;
    el["open-file-button"].disabled = true;
    try {
      await request(`/api/open?id=${encodeURIComponent(state.selectedId)}`, {
        method: "POST",
        headers: { "X-KB-Viewer": "1" },
      });
      showToast("Opened in the default Markdown application");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      el["open-file-button"].disabled = false;
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
