/**
 * graph.js — Knowledge Graph Explorer
 *
 * Features:
 *   • Sigma.js WebGL renderer for 1000+ nodes at 60fps
 *   • k-NN semantic edges with adjustable similarity threshold
 *   • HDBSCAN cluster colours from backend
 *   • Citation edge overlay (amber, dashed)
 *   • Dynamic focus mode: select papers → mean embedding distance colouring
 *   • Structural hole highlighting
 *   • Paper detail panel with similar-papers list
 *   • Search/filter by title
 */

"use strict";

// ─── Auth token ────────────────────────────────────────────────────────────
const TOKEN = (() => {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("token");
  if (fromUrl) {
    sessionStorage.setItem("auth_token", fromUrl);
    // Clean only the token from URL to preserve other params like neighbor_id
    const newParams = new URLSearchParams(window.location.search);
    newParams.delete("token");
    const searchString = newParams.toString();
    const clean =
      window.location.pathname + (searchString ? "?" + searchString : "");
    window.history.replaceState({}, "", clean);
    return fromUrl;
  }
  return sessionStorage.getItem("auth_token") || "";
})();

async function apiFetch(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "x-auth-token": TOKEN,
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json();
}

// ─── State ─────────────────────────────────────────────────────────────────
let graphData = null; // raw API response
let citationData = null; // citation edges
let renderer = null; // Sigma instance
let graph = null; // Graphology instance
let selectedNodes = new Set(); // currently selected paper IDs
let focusDistances = null; // {id → similarity} from focus API
let highlightedCluster = null; // cluster filter
let showCitations = false;
let showGaps = false;
let showLabels = true;
let thresholdRaw = 50; // slider value 0-100
let searchFilter = "";
let currentDetail = null; // paper id in detail panel

// ─── DOM refs ──────────────────────────────────────────────────────────────
const loadingOverlay = document.getElementById("loading-overlay");
const statusText = document.getElementById("status-text");
const statusDot = document.getElementById("status-dot");
const buildStatus = document.getElementById("build-status");
const statNodes = document.getElementById("stat-nodes");
const statEdges = document.getElementById("stat-edges");
const statClusters = document.getElementById("stat-clusters");
const clusterLegend = document.getElementById("cluster-legend");
const gapsSection = document.getElementById("gaps-section");
const gapsList = document.getElementById("gaps-list");
const detailPanel = document.getElementById("detail-panel");
const detailTitle = document.getElementById("detail-title");
const detailMeta = document.getElementById("detail-meta");
const detailSummary = document.getElementById("detail-summary");
const neighborList = document.getElementById("neighbor-list");
const focusInfo = document.getElementById("focus-info");
const focusCount = document.getElementById("focus-count");
const btnFocus = document.getElementById("btn-focus");
const btnClearFocus = document.getElementById("btn-clear-focus");
const tooltip = document.getElementById("tooltip");
const searchBar = document.getElementById("search-bar");
const thresholdSlider = document.getElementById("threshold-slider");
const thresholdVal = document.getElementById("threshold-val");

// New Progress Bar Refs
const pbAuthors = document.getElementById("pb-authors");
const valAuthors = document.getElementById("val-authors");
const pbYear = document.getElementById("pb-year");
const valYear = document.getElementById("val-year");
const pbSummary = document.getElementById("pb-summary");
const valSummary = document.getElementById("val-summary");
const pbDoi = document.getElementById("pb-doi");
const valDoi = document.getElementById("val-doi");

// ─── Helpers ───────────────────────────────────────────────────────────────
function setStatus(msg, state = "building") {
  statusText.textContent = msg;
  buildStatus.className = `build-status ${state}`;
  if (state === "building") {
    statusDot.className = "status-dot pulse";
  } else {
    statusDot.className = "status-dot";
  }
}

function hideLoading() {
  loadingOverlay.classList.add("hidden");
}

function showLoading(msg = "Building semantic graph…") {
  loadingOverlay.querySelector(".loading-text").textContent = msg;
  loadingOverlay.classList.remove("hidden");
}

function shortenTitle(t, max = 50) {
  return t && t.length > max ? t.slice(0, max) + "…" : t || "Untitled";
}

function getNodeLabel(data) {
  if (!data) return "";
  let author = "";
  if (data.authors && data.authors.trim()) {
    let raw = data.authors;
    if (Array.isArray(raw)) raw = raw[0];
    // Split by common delimiters: comma, semicolon, "and", "&"
    const parts = raw.split(/[,;]|\band\b|&/i);
    author = parts[0]
      .trim()
      .replace(/\bet al\.?\b/gi, "")
      .trim();
  } else if (data.pdf_filename) {
    // Fallback: extract from filename "Hooge et al. - 2015 - ..."
    const match = data.pdf_filename.match(/^([^-]+)\s*-\s*(\d{4})/);
    if (match) {
      author = match[1]
        .trim()
        .replace(/\bet al\.?\b/gi, "")
        .trim();
    }
  }

  const year = data.year || data.pdf_filename?.match(/\d{4}/)?.[0] || "";

  // If we have author and year, use classic citation format
  if (author && year) return `(${author}, ${year})`;
  // If we have author only
  if (author) return `(${author})`;
  // Fallback: use truncated title
  if (data.title && data.title !== "Unknown") {
    return shortenTitle(data.title, 30);
  }
  return "(Unknown)";
}

function sliderToThreshold(v) {
  // Map 0-100 → 0.0 - 0.95
  return (v / 100) * 0.95;
}

// ─── Bootstrap ─────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  if (!TOKEN) {
    window.location.href = "/ui?redirect=/ui/graph.html";
    return;
  }
  const params = new URLSearchParams(window.location.search);
  const neighborId = params.get("neighbor_id");
  if (neighborId) {
    // Lower threshold for neighbor graphs (BoW similarity is typically 0.05-0.3)
    thresholdRaw = 0;
    if (thresholdSlider) {
      thresholdSlider.value = 0;
    }
    if (thresholdVal) {
      thresholdVal.textContent = "0.0";
    }
    loadNeighborGraph(neighborId);
  } else {
    loadGraph();
  }
  wireControls();
});

async function loadNeighborGraph(neighborId) {
  console.log("[QuickGraph] loadNeighborGraph called with:", neighborId);
  showLoading("Building neighbor graph…");
  setStatus("Loading neighbors…", "building");

  try {
    console.log("[QuickGraph] Fetching /api/graph/neighbors/" + neighborId);
    const data = await apiFetch(`/api/graph/neighbors/${neighborId}`);
    console.log("[QuickGraph] API response:", { nodes: data.nodes?.length, edges: data.edges?.length, source_id: data.source_id });
    if (!data.nodes || data.nodes.length === 0) {
      setStatus("No neighbors found — this paper may not have a BoW index.", "error");
      hideLoading();
      return;
    }

    const sourceNode = data.nodes.find((n) => n.is_source || n.id === neighborId);
    const otherNodes = data.nodes.filter((n) => n !== sourceNode);

    if (sourceNode) {
      sourceNode.x = 0;
      sourceNode.y = 0;
      sourceNode.cluster = 1;
      sourceNode.cluster_color = "#f59e0b";
      sourceNode.degree = otherNodes.length;
      sourceNode.hash_id = sourceNode.id;
    }

    const radius = 0.8;
    otherNodes.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(1, otherNodes.length);
      n.x = radius * Math.cos(angle) + (Math.random() * 0.1 - 0.05);
      n.y = radius * Math.sin(angle) + (Math.random() * 0.1 - 0.05);
      n.cluster = 0;
      n.cluster_color = "#6366f1";
      n.degree = 1;
      n.hash_id = n.id;
    });

    // Minimal stats for UI
    data.stats = {
      n_nodes: data.nodes.length,
      n_edges: data.edges.length,
      n_clusters: 2,
    };

    graphData = data;

    // Slight delay to ensure DOM and layout container dimensions are fully ready
    requestAnimationFrame(() => {
      renderGraph();

      // Custom force-directed spring layout in normalized coordinate space
      if (graph) {
        const nodes = graph.nodes();
        const velocities = {};
        nodes.forEach((node) => (velocities[node] = { x: 0, y: 0 }));

        const cRep = 0.0005;
        const cAtt = 0.08;
        const gravity = 0.02;
        const damping = 0.7;

        for (let iter = 0; iter < 100; iter++) {
          for (let i = 0; i < nodes.length; i++) {
            const n1 = nodes[i];
            const pos1 = { x: graph.getNodeAttribute(n1, "x"), y: graph.getNodeAttribute(n1, "y") };
            for (let j = i + 1; j < nodes.length; j++) {
              const n2 = nodes[j];
              const pos2 = { x: graph.getNodeAttribute(n2, "x"), y: graph.getNodeAttribute(n2, "y") };
              const dx = pos1.x - pos2.x;
              const dy = pos1.y - pos2.y;
              const distSq = dx * dx + dy * dy + 1e-4;
              const dist = Math.sqrt(distSq);
              const force = cRep / distSq;
              const fx = (dx / dist) * force;
              const fy = (dy / dist) * force;
              if (n1 !== neighborId) {
                velocities[n1].x += fx;
                velocities[n1].y += fy;
              }
              if (n2 !== neighborId) {
                velocities[n2].x -= fx;
                velocities[n2].y -= fy;
              }
            }
          }

          graph.forEachEdge((edge, attributes, source, target) => {
            const posS = { x: graph.getNodeAttribute(source, "x"), y: graph.getNodeAttribute(source, "y") };
            const posT = { x: graph.getNodeAttribute(target, "x"), y: graph.getNodeAttribute(target, "y") };
            const dx = posS.x - posT.x;
            const dy = posS.y - posT.y;
            const dist = Math.sqrt(dx * dx + dy * dy) + 1e-4;
            const weight = attributes.weight || 0.5;
            const force = cAtt * dist * weight;
            const fx = (dx / dist) * force;
            const fy = (dy / dist) * force;
            if (source !== neighborId) {
              velocities[source].x -= fx;
              velocities[source].y -= fy;
            }
            if (target !== neighborId) {
              velocities[target].x += fx;
              velocities[target].y += fy;
            }
          });

          nodes.forEach((node) => {
            if (node === neighborId) return;
            const px = graph.getNodeAttribute(node, "x");
            const py = graph.getNodeAttribute(node, "y");
            velocities[node].x -= px * gravity;
            velocities[node].y -= py * gravity;
            const nx = px + velocities[node].x;
            const ny = py + velocities[node].y;
            velocities[node].x *= damping;
            velocities[node].y *= damping;
            graph.setNodeAttribute(node, "x", nx);
            graph.setNodeAttribute(node, "y", ny);
          });
        }
      }

      if (renderer) renderer.refresh();
      updateStats();
      const focalTitle = sourceNode ? shortenTitle(sourceNode.title, 35) : neighborId.substring(0, 8);
      setStatus(`Neighborhood Graph: ${focalTitle} (${data.nodes.length} papers)`, "ready");
      hideLoading();

      // Reset camera view onto radial origin
      setTimeout(() => {
        if (renderer) {
          try {
            renderer.getCamera().animate({ x: 0, y: 0, ratio: 1.0 }, { duration: 600 });
          } catch (e) {}
        }
      }, 200);
    });
  } catch (err) {
    setStatus("Error loading neighbors", "error");
    console.error(err);
  }
}

async function loadGraph(forceRebuild = false) {
  showLoading();
  setStatus("Loading graph…", "building");

  try {
    let data = await apiFetch("/api/graph/semantic");

    // If the server is still building, poll until ready
    let retries = 0;
    while (data.status === "building" && retries < 30) {
      setStatus("Graph building on server… retry in 5s", "building");
      await sleep(5000);
      data = await apiFetch("/api/graph/semantic");
      retries++;
    }

    if (!data.nodes || data.nodes.length === 0) {
      setStatus("No papers in library yet.", "error");
      hideLoading();
      return;
    }

    graphData = data;

    requestAnimationFrame(() => {
      renderGraph();
      buildLegend();
      buildGapsPanel();
      updateStats();
      setStatus(`Ready — ${data.stats.n_nodes} papers`, "ready");
      hideLoading();
    });
  } catch (err) {
    setStatus("Error loading graph", "error");
    loadingOverlay.querySelector(".loading-text").textContent =
      `Error: ${err.message}`;
    console.error(err);
  }
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// ─── Render Graph with Sigma.js ────────────────────────────────────────────
function renderGraph() {
  const container = document.getElementById("sigma-canvas");
  if (!container) { console.error("[renderGraph] #sigma-canvas not found!"); return; }

  console.log("[renderGraph] container dims:", container.offsetWidth, "x", container.offsetHeight);

  // Basic sanity check: WebGL often fails if container has no size
  if (container.offsetWidth === 0 || container.offsetHeight === 0) {
    console.warn("Sigma container has no dimensions. Delaying render...");
    setTimeout(renderGraph, 100);
    return;
  }

  if (renderer) {
    try {
      renderer.kill();
    } catch (e) {}
    graph = null;
    renderer = null;
  }

  if (typeof Sigma === "undefined" || typeof graphology === "undefined") {
    console.error("[renderGraph] Sigma or graphology not loaded!");
    setStatus("Graph library not loaded (CDN error)", "error");
    return;
  }

  graph = new graphology.Graph({ multi: false, type: "undirected" });

  const threshold = sliderToThreshold(thresholdRaw);
  console.log("[renderGraph] thresholdRaw:", thresholdRaw, "→ threshold:", threshold);
  const nodeMap = {};

  // Add nodes
  for (const n of graphData.nodes) {
    const size = 3 + Math.min((n.degree || 0) * 0.4, 8);
    const visible = passesFilter(n);
    graph.addNode(n.id, {
      x: n.x || Math.random() * 2 - 1,
      y: n.y || Math.random() * 2 - 1,
      size,
      color: n.cluster_color || "#6366f1",
      label: showLabels ? getNodeLabel(n) : "",
      hidden: !visible,
      _data: n,
    });
    nodeMap[n.id] = n;
  }

  // Add semantic edges
  let edgesAdded = 0;
  for (const e of graphData.edges) {
    if (e.weight < threshold) continue;
    if (!graph.hasNode(e.source) || !graph.hasNode(e.target)) continue;
    if (graph.hasEdge(e.source, e.target)) continue;
    try {
      graph.addEdge(e.source, e.target, {
        weight: e.weight,
        size: Math.max(0.3, e.weight * 1.5),
        color: `rgba(99,102,241,${Math.min(e.weight * 0.5, 0.4)})`,
      });
      edgesAdded++;
    } catch {}
  }
  console.log("[renderGraph] Graph built:", graph.order, "nodes,", edgesAdded, "edges added (threshold:", threshold.toFixed(3), ")");

  // Add citation edges (if loaded and toggled)
  if (showCitations && citationData) {
    for (const ce of citationData.edges) {
      if (!graph.hasNode(ce.source) || !graph.hasNode(ce.target)) continue;
      if (graph.hasEdge(ce.source, ce.target)) continue;
      try {
        graph.addEdge(ce.source, ce.target, {
          size: 1.2,
          color: "rgba(245,158,11,0.55)",
        });
      } catch {}
    }
  }

  // Set source node to be very large
  if (graphData.source_id && graph.hasNode(graphData.source_id)) {
    graph.setNodeAttribute(graphData.source_id, "size", 15);
    graph.setNodeAttribute(graphData.source_id, "color", "#f59e0b");
    const currentLabel = graph.getNodeAttribute(graphData.source_id, "label") || "";
    if (!currentLabel.startsWith("🌟")) {
      graph.setNodeAttribute(
        graphData.source_id,
        "label",
        `🌟 ${currentLabel}`,
      );
    }
  }

  try {
    renderer = new Sigma(graph, container, {
      renderEdgeLabels: false,
      defaultEdgeColor: "rgba(99,102,241,0.2)",
      defaultNodeColor: "#6366f1",
      labelColor: { color: "#ffffff" },
      labelSize: 14,
      labelWeight: "600",
      labelFont: "Inter, sans-serif",
      zoomToSizeRatioFunction: (ratio) => (ratio < 1 ? 1 : Math.sqrt(ratio)),
      minCameraRatio: 0.05,
      maxCameraRatio: 10,
      zIndex: true,
    });
  } catch (err) {
    console.error("Sigma construction failed:", err);
    setStatus(
      "WebGL initialization failed. Try refreshing or check browser compatibility.",
      "error",
    );
    return;
  }

  // Hover tooltip
  renderer.on("enterNode", ({ node }) => {
    const n = graph.getNodeAttributes(node);
    const data = n._data;
    tooltip.innerHTML = `<strong>${shortenTitle(data.title, 60)}</strong><span>${data.authors || ""} ${data.year ? `(${data.year})` : ""}</span>`;
    tooltip.classList.add("visible");
    document.body.style.cursor = "pointer";
  });

  renderer.on("leaveNode", () => {
    tooltip.classList.remove("visible");
    document.body.style.cursor = "default";
  });

  // Edge hover tooltip
  renderer.on("enterEdge", ({ edge }) => {
    const source = graph.source(edge);
    const target = graph.target(edge);
    const sData = graph.getNodeAttribute(source, "_data");
    const tData = graph.getNodeAttribute(target, "_data");
    const weight = graph.getEdgeAttribute(edge, "weight");

    let info = `<span>${getNodeLabel(sData)} ↔ ${getNodeLabel(tData)}</span>`;
    if (weight !== undefined) {
      info += `<span>Similarity: ${(weight * 100).toFixed(0)}%</span>`;
    } else {
      info = `<strong>Citation</strong>` + info;
    }

    tooltip.innerHTML =
      (weight !== undefined ? `<strong>Semantic Connection</strong>` : "") +
      info;
    tooltip.classList.add("visible");
  });

  renderer.on("leaveEdge", () => {
    tooltip.classList.remove("visible");
  });

  // Move tooltip with mouse
  document.addEventListener("mousemove", (e) => {
    tooltip.style.left = `${e.clientX + 14}px`;
    tooltip.style.top = `${e.clientY - 8}px`;
  });

  // Click node → detail panel / selection
  renderer.on("clickNode", ({ node, event }) => {
    const shiftHeld = event && (event.original?.shiftKey || event.shiftKey);

    if (shiftHeld) {
      // Multi-select mode
      if (selectedNodes.has(node)) {
        selectedNodes.delete(node);
      } else {
        selectedNodes.add(node);
      }
      updateSelectionVisuals();
      updateFocusUI();
    } else {
      // Single click → show detail, clear multi-select
      selectedNodes.clear();
      selectedNodes.add(node);
      updateSelectionVisuals();
      updateFocusUI();
      showDetail(node);
    }
  });

  // Click canvas background → deselect
  renderer.on("clickStage", () => {
    selectedNodes.clear();
    updateSelectionVisuals();
    updateFocusUI();
    if (focusDistances) {
      // keep focus colouring
    }
  });
}

function passesFilter(n) {
  if (searchFilter) {
    const s = searchFilter.toLowerCase();
    const matchTitle = n.title?.toLowerCase().includes(s);
    const matchAuthors = n.authors?.toLowerCase().includes(s);
    const matchYear = n.year?.toString().includes(s);
    if (!matchTitle && !matchAuthors && !matchYear) return false;
  }
  if (highlightedCluster !== null && n.cluster !== highlightedCluster)
    return false;
  return true;
}

// ─── Selection Visuals ─────────────────────────────────────────────────────
function updateSelectionVisuals() {
  if (!graph || !renderer) return;

  graph.forEachNode((node, attrs) => {
    const data = attrs._data;
    let color = data.cluster_color;
    let size = 3 + Math.min(data.degree * 0.4, 8);
    let hidden = !passesFilter(data);

    if (focusDistances) {
      const sim = focusDistances[node]?.similarity ?? 0;
      const alpha = Math.max(0.15, sim);
      color = interpolateColor(data.cluster_color, "#ffffff", sim * 0.4);
      size = 3 + Math.min(data.degree * 0.4 + sim * 6, 14);
      hidden = !passesFilter(data) || sim < 0.2;
    }

    if (selectedNodes.has(node)) {
      color = "#ffffff";
      size *= 1.6;
      hidden = false;
    }

    graph.setNodeAttribute(node, "color", color);
    graph.setNodeAttribute(node, "size", size);
    graph.setNodeAttribute(node, "hidden", hidden);
    graph.setNodeAttribute(node, "label", showLabels ? getNodeLabel(data) : "");
  });

  renderer.refresh();
}

function interpolateColor(hex, target, t) {
  const r1 = parseInt(hex.slice(1, 3), 16);
  const g1 = parseInt(hex.slice(3, 5), 16);
  const b1 = parseInt(hex.slice(5, 7), 16);
  const r2 = target === "#ffffff" ? 255 : 100;
  const g2 = target === "#ffffff" ? 255 : 102;
  const b2 = target === "#ffffff" ? 255 : 241;
  const r = Math.round(r1 + (r2 - r1) * t);
  const g = Math.round(g1 + (g2 - g1) * t);
  const b = Math.round(b1 + (b2 - b1) * t);
  return `rgb(${r},${g},${b})`;
}

// ─── Focus Mode ────────────────────────────────────────────────────────────
async function applyFocus() {
  if (selectedNodes.size === 0) return;
  const ids = Array.from(selectedNodes);
  setStatus("Computing focus…", "building");
  try {
    const res = await apiFetch("/api/graph/focus", {
      method: "POST",
      body: JSON.stringify({ paper_ids: ids }),
    });
    focusDistances = {};
    for (const entry of res.distances) {
      focusDistances[entry.id] = entry;
    }
    updateSelectionVisuals();
    setStatus("Focus applied", "ready");
    focusInfo.classList.add("active");
    focusCount.textContent = `${ids.length} paper${ids.length > 1 ? "s" : ""}`;
    btnClearFocus.disabled = false;
  } catch (err) {
    setStatus("Focus failed", "error");
    console.error(err);
  }
}

function clearFocus() {
  focusDistances = null;
  focusInfo.classList.remove("active");
  btnClearFocus.disabled = true;
  selectedNodes.clear();
  updateSelectionVisuals();
  updateFocusUI();
  setStatus(`Ready — ${graphData.stats.n_nodes} papers`, "ready");
}

function updateFocusUI() {
  const count = selectedNodes.size;
  focusCount.textContent = `${count} paper${count !== 1 ? "s" : ""}`;
  btnFocus.disabled = count === 0;
  focusInfo.classList.toggle("active", count > 0);
}

// ─── Citation Overlay ──────────────────────────────────────────────────────
async function toggleCitations(on) {
  showCitations = on;
  if (on && !citationData) {
    setStatus("Loading citations…", "building");
    try {
      citationData = await apiFetch("/api/graph/citations");
      setStatus(
        `Citations: ${citationData.edges.length} links loaded`,
        "ready",
      );
    } catch (err) {
      setStatus("Citation load failed", "error");
      document.getElementById("toggle-citations").checked = false;
      showCitations = false;
      return;
    }
  }
  renderGraph();
}

// ─── Structural Holes ──────────────────────────────────────────────────────
function buildGapsPanel() {
  if (!graphData.gaps || graphData.gaps.length === 0) return;
  gapsSection.style.display = "";
  gapsList.innerHTML = "";
  for (const gap of graphData.gaps.slice(0, 10)) {
    const card = document.createElement("div");
    card.className = "gap-card";
    card.innerHTML = `
      <div class="gap-score">Gap score: ${gap.gap_score.toFixed(3)}</div>
      <div class="gap-desc">
        Cluster ${gap.cluster_a} ↔ Cluster ${gap.cluster_b}<br>
        Similarity: ${(gap.semantic_similarity * 100).toFixed(0)}% &bull;
        Inter-link density: ${(gap.inter_edge_density * 100).toFixed(2)}%
      </div>`;
    card.addEventListener("click", () => highlightGap(gap));
    gapsList.appendChild(card);
  }
}

function highlightGap(gap) {
  if (!graph || !renderer) return;
  graph.forEachNode((node, attrs) => {
    const c = attrs._data.cluster;
    const isInGap = c === gap.cluster_a || c === gap.cluster_b;
    graph.setNodeAttribute(node, "hidden", !isInGap);
    if (isInGap) {
      const color = c === gap.cluster_a ? "#6366f1" : "#f59e0b";
      graph.setNodeAttribute(node, "color", color);
      graph.setNodeAttribute(node, "size", 6);
    }
  });
  renderer.refresh();
}

// ─── Cluster Legend ────────────────────────────────────────────────────────
function buildLegend() {
  clusterLegend.innerHTML = "";
  if (!graphData.clusters) return;
  for (const c of graphData.clusters) {
    const item = document.createElement("div");
    item.className = "legend-item";
    item.innerHTML = `
      <span class="legend-dot" style="background:${c.color}"></span>
      <span>Cluster ${c.id} <small>(${c.count})</small></span>`;
    item.addEventListener("click", () => {
      if (highlightedCluster === c.id) {
        highlightedCluster = null;
        item.classList.remove("active");
        document
          .querySelectorAll(".legend-item")
          .forEach((el) => el.classList.remove("active"));
      } else {
        highlightedCluster = c.id;
        document
          .querySelectorAll(".legend-item")
          .forEach((el) => el.classList.remove("active"));
        item.classList.add("active");
      }
      updateSelectionVisuals();
    });
    clusterLegend.appendChild(item);
  }
}

// ─── Paper Detail Panel ────────────────────────────────────────────────────
function showDetail(nodeId) {
  currentDetail = nodeId;
  const attrs = graph.getNodeAttributes(nodeId);
  const data = attrs._data;

  detailTitle.textContent = data.title || "Untitled";
  detailMeta.innerHTML = `
    ${data.authors ? `<div>✍ ${data.authors}</div>` : ""}
    ${data.year ? `<div>📅 ${data.year}</div>` : ""}
    ${data.doi ? `<div>🔗 <a href="https://doi.org/${data.doi}" target="_blank" style="color:var(--accent)">${data.doi}</a></div>` : ""}
    ${
      data.keywords
        ? `<div style="margin-top:6px;">${data.keywords
            .split(",")
            .slice(0, 5)
            .map(
              (k) =>
                `<span class="detail-badge" style="background:rgba(99,102,241,0.12);color:#8892a4;border:1px solid rgba(99,102,241,0.2)">${k.trim()}</span>`,
            )
            .join("")}</div>`
        : ""
    }
  `;
  detailSummary.textContent = data.summary || "No summary available.";

  // Reset citation button state
  const citationBtn = document.getElementById("detail-add-citation");
  if (citationBtn) {
    citationBtn.textContent = "📎 Add to Bibliography";
    citationBtn.classList.remove("citation-ready");
    citationBtn.removeAttribute("data-citation-key");
    citationBtn.removeAttribute("title");
    citationBtn.disabled = false;
    citationBtn.removeAttribute("aria-busy");
  }

  // Find neighbours via graph edges
  const neighbors = [];
  graph.forEachNeighbor(nodeId, (neighbor, nAttrs) => {
    const edgeAttrs = graph.getEdgeAttributes(
      graph.edges(nodeId, neighbor)[0] || graph.edges(neighbor, nodeId)[0],
    );
    neighbors.push({
      id: neighbor,
      sim: edgeAttrs?.weight ?? 0,
      title: nAttrs._data.title,
    });
  });
  neighbors.sort((a, b) => b.sim - a.sim);

  neighborList.innerHTML = "";
  for (const nb of neighbors.slice(0, 8)) {
    const el = document.createElement("div");
    el.className = "neighbor-item";
    el.innerHTML = `
      <span class="neighbor-sim">${(nb.sim * 100).toFixed(0)}%</span>
      <span class="neighbor-title">${shortenTitle(nb.title, 40)}</span>`;
    el.addEventListener("click", () => {
      renderer
        .getCamera()
        .animate(
          {
            x: graph.getNodeAttribute(nb.id, "x"),
            y: graph.getNodeAttribute(nb.id, "y"),
            ratio: 0.25,
          },
          { duration: 500 },
        );
      showDetail(nb.id);
    });
    neighborList.appendChild(el);
  }

  detailPanel.classList.remove("hidden");
}

// PDF open
document.getElementById("detail-open-pdf").addEventListener("click", () => {
  if (currentDetail) {
    window.open(`/api/pdf/${currentDetail}?token=${TOKEN}`, "_blank");
  }
});

// Add to bibliography
document
  .getElementById("detail-add-citation")
  .addEventListener("click", async () => {
    if (!currentDetail) return;

    const btn = document.getElementById("detail-add-citation");

    // Convert to copy action if already cited
    if (btn.classList.contains("citation-ready")) {
      const citationKey = btn.dataset.citationKey;
      if (!citationKey) return;
      if (btn.textContent === "Copied!") return;

      try {
        await navigator.clipboard.writeText(`\\cite{${citationKey}}`);
        btn.textContent = "Copied!";
        btn.style.background = "#10b981"; // success color
        setTimeout(() => {
          btn.textContent = `\\cite{${citationKey}}`;
          btn.style.background = "";
        }, 2000);
      } catch (e) {
        console.error("Failed to copy citation:", e);
      }
      return;
    }

    const project = sessionStorage.getItem("active_project") || "default";

    btn.textContent = "Adding...";
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");

    try {
      const response = await apiFetch("/api/citation/add", {
        method: "POST",
        body: JSON.stringify({ hash_id: currentDetail, project }),
      });

      btn.textContent = "✓ Added!";
      btn.classList.add("citation-ready");
      btn.dataset.citationKey = response.bib_key;
      btn.setAttribute("title", "Click to copy citation");
      setTimeout(() => {
        btn.textContent = `\\cite{${response.bib_key}}`;
      }, 1000);
    } catch (err) {
      alert("Failed to add citation: " + err.message);
      btn.textContent = "Error";
    } finally {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
    }
  });

// Close detail
document.getElementById("detail-close").addEventListener("click", () => {
  detailPanel.classList.add("hidden");
  currentDetail = null;
});

// Global Escape to close detail panel
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !detailPanel.classList.contains("hidden")) {
    detailPanel.classList.add("hidden");
    currentDetail = null;
  }
});

// ─── Stats ─────────────────────────────────────────────────────────────────
function updateStats() {
  const stats = graphData.stats;
  statNodes.textContent = stats.n_nodes.toLocaleString();
  statEdges.textContent = stats.n_edges.toLocaleString();
  statClusters.textContent = stats.n_clusters;

  // Detailed progress
  const total = stats.n_nodes;

  const updateBar = (el, valEl, count) => {
    const pct = total > 0 ? (count / total) * 100 : 0;
    el.style.width = `${pct}%`;
    valEl.textContent = `${count}/${total}`;

    // Dynamic coloring based on completion
    if (pct === 100) el.style.background = "var(--accent2)";
    else if (pct > 75) el.style.background = "var(--accent)";
    else if (pct > 0) el.style.background = "var(--amber)";
    else el.style.background = "var(--text-muted)";
  };

  updateBar(pbAuthors, valAuthors, stats.n_with_authors || 0);
  updateBar(pbYear, valYear, stats.n_with_year || 0);
  updateBar(pbSummary, valSummary, stats.n_with_summary || 0);
  updateBar(pbDoi, valDoi, stats.n_with_doi || 0);
}

// ─── Wire Controls ─────────────────────────────────────────────────────────
function wireControls() {
  // Threshold slider
  thresholdSlider.addEventListener("input", () => {
    thresholdRaw = parseInt(thresholdSlider.value);
    const thr = sliderToThreshold(thresholdRaw);
    thresholdVal.textContent = thr.toFixed(2);
    if (graphData) renderGraph();
  });

  // Toggles
  document
    .getElementById("toggle-citations")
    .addEventListener("change", (e) => toggleCitations(e.target.checked));

  document.getElementById("toggle-gaps").addEventListener("change", (e) => {
    showGaps = e.target.checked;
    gapsSection.style.display = showGaps ? "" : "none";
  });

  document.getElementById("toggle-labels").addEventListener("change", (e) => {
    showLabels = e.target.checked;
    if (graph) updateSelectionVisuals();
  });

  // Focus buttons
  btnFocus.addEventListener("click", applyFocus);
  btnClearFocus.addEventListener("click", clearFocus);

  // Rebuild button
  document.getElementById("btn-rebuild").addEventListener("click", async () => {
    setStatus("Triggering rebuild…", "building");
    try {
      await apiFetch("/api/graph/rebuild", { method: "POST" });
      graphData = null;
      loadGraph();
    } catch (err) {
      setStatus("Rebuild failed", "error");
    }
  });

  // Search
  searchBar.addEventListener("input", (e) => {
    searchFilter = e.target.value.toLowerCase().trim();
    if (graph) updateSelectionVisuals();
  });
}
