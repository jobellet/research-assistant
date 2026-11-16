// Discover tab: search online databases (arXiv, OpenAlex, Semantic Scholar,
// Crossref), find papers related to a library paper or to highlighted text,
// and download open-access PDFs into the library inbox.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const input = $("discover-input");
  const resultsEl = $("discover-results");
  const statusEl = $("discover-status");
  if (!input || !resultsEl) return;

  const lastResults = [];

  function headers() {
    return {
      "Content-Type": "application/json",
      "x-auth-token": (window.CONFIG && window.CONFIG.AUTH_TOKEN) || "",
    };
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  function selectedSources() {
    return [...document.querySelectorAll(".discover-sources input:checked")].map((i) => i.value);
  }

  function setStatus(msg) {
    statusEl.textContent = msg || "";
  }

  function showTab() {
    if (window.switchSidePanel) window.switchSidePanel("discover");
    const sp = document.querySelector(".side-panel");
    if (sp && window.appState && window.appState.isMobile) sp.classList.add("mobile-active");
  }

  const SOURCE_LABEL = {
    arxiv: "arXiv", openalex: "OpenAlex", semantic_scholar: "S2", crossref: "Crossref",
    semantic_scholar_recommendations: "S2 similar", semantic_scholar_citations: "cites it",
    openalex_related: "OpenAlex related",
  };

  function render(data, heading) {
    lastResults.length = 0;
    const results = (data && data.results) || [];
    results.forEach((r) => lastResults.push(r));
    const per = data && data.per_source
      ? Object.entries(data.per_source).map(([k, v]) => `${SOURCE_LABEL[k] || k}: ${v}`).join(" · ")
      : "";
    setStatus(`${results.length} papers${per ? " — " + per : ""}`);
    if (!results.length) {
      resultsEl.innerHTML = `<div class="empty-state" style="text-align:center;padding:2rem 1rem">
        <div class="text-secondary">No results. Databases may be rate-limiting; try again in a minute or select other sources.</div></div>`;
      return;
    }
    const head = heading ? `<div class="discover-meta" style="margin-bottom:0.75rem">${heading}</div>` : "";
    resultsEl.innerHTML = head + results.map((r, i) => {
      const authors = (r.authors || []).slice(0, 3).join(", ") + ((r.authors || []).length > 3 ? " et al." : "");
      const ident = r.arxiv_id ? `arXiv:${esc(r.arxiv_id)}` : (r.doi ? `doi:${esc(r.doi)}` : "");
      const badges = (r.sources || []).map((s) => `<span class="source-badge">${esc(SOURCE_LABEL[s] || s)}</span>`).join("");
      const link = r.url || (r.doi ? `https://doi.org/${r.doi}` : "");
      const action = r.in_library
        ? `<span class="source-badge in-library">✓ in library</span>`
        : (r.downloadable
            ? `<button class="view-btn" style="background: var(--accent-color); color: white" onclick="discoverFetch(${i}, this)">Add to library</button>`
            : `<span class="source-badge" title="No open-access PDF found">no open PDF</span>`);
      return `<div class="result-card" style="padding:1rem;margin-bottom:0.75rem">
        <div class="result-title" style="font-size:0.95rem;margin-bottom:0.25rem">${esc(r.title)}</div>
        <div class="discover-meta">${esc(authors)} (${esc(r.year || "n.d.")})${r.venue ? " · " + esc(r.venue) : ""}${r.citation_count != null ? " · " + esc(r.citation_count) + " citations" : ""}</div>
        ${r.abstract ? `<div class="discover-abstract">${esc(r.abstract)}</div>` : ""}
        <div class="result-footer" style="justify-content:space-between;align-items:center">
          <div>${badges}<span class="discover-meta">${ident}</span></div>
          <div style="display:flex;gap:0.3rem">
            ${link ? `<a class="view-btn" href="${esc(link)}" target="_blank" rel="noopener">Open</a>` : ""}
            ${action}
          </div>
        </div></div>`;
    }).join("");
  }

  const browserMode = () => window.ProjectStore && window.ProjectStore.isBrowserMode();

  // Without a server the same searches run in the browser (phone-library.js)
  function browserCall(path, opts) {
    const body = opts && opts.body ? JSON.parse(opts.body) : {};
    if (path.startsWith("/api/discover/search")) return window.PhoneLibrary.discover("search", body);
    if (path.startsWith("/api/discover/text")) return window.PhoneLibrary.discover("text", body);
    const hash = decodeURIComponent(path.split("/").pop());
    return window.PhoneLibrary.discover("related", { hash });
  }

  async function call(path, opts, heading, busyMsg) {
    showTab();
    setStatus(busyMsg);
    resultsEl.innerHTML = `<div class="text-secondary" style="text-align:center;margin-top:2rem">${esc(busyMsg)}</div>`;
    try {
      let data;
      if (browserMode()) {
        data = await browserCall(path, opts);
      } else {
        const res = await fetch(path, { headers: headers(), ...opts });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.status);
        data = await res.json();
      }
      render(data, heading(data));
    } catch (e) {
      console.error("Discover error:", e);
      setStatus("Search failed: " + e.message);
      resultsEl.innerHTML = "";
    }
  }

  function search() {
    const q = input.value.trim();
    if (!q) return input.focus();
    call("/api/discover/search", {
      method: "POST",
      body: JSON.stringify({ query: q, sources: selectedSources(), limit: 20 }),
    }, () => `Results for <b>${esc(q)}</b>`, "Searching online databases…");
  }

  function fromSelection() {
    const text = (window.appState && window.appState.lastSelection) || window.getSelection().toString() ||
      (browserMode() ? (document.getElementById("latex-editor").value.slice(
        document.getElementById("latex-editor").selectionStart, document.getElementById("latex-editor").selectionEnd)) : "");
    if (!text || text.trim().length < 10) {
      setStatus("Highlight a sentence in the editor first.");
      return showTab();
    }
    call("/api/discover/text", { method: "POST", body: JSON.stringify({ text, limit: 20 }) },
      (d) => `Literature for the highlighted text — key terms: <b>${esc((d.terms || []).join(", "))}</b>`,
      "Looking for literature on the highlighted text…");
  }

  window.discoverRelated = (hashId) => {
    call(`/api/discover/related/${encodeURIComponent(hashId)}`, { method: "GET" },
      (d) => `Papers related to <b>${esc((d.seed && d.seed.title) || "")}</b>`,
      "Finding related papers (Semantic Scholar, OpenAlex, arXiv)…");
  };

  window.discoverFetch = async (index, btn) => {
    const cand = lastResults[index];
    if (!cand) return;
    btn.disabled = true;
    if (browserMode()) {
      window.PhoneLibrary.queueAdd(cand);
      btn.textContent = "Queued for your computer";
      btn.title = "Your computer downloads it into the library at its next Google Drive sync";
      return;
    }
    btn.textContent = "Downloading…";
    try {
      const res = await fetch("/api/discover/fetch", {
        method: "POST", headers: headers(), body: JSON.stringify({ candidate: cand, process: true }),
      });
      const data = await res.json();
      const labels = {
        downloaded: "Added — processing…", exists: "Already in inbox", in_library: "✓ in library",
        no_pdf: "No open PDF", failed: "Download failed",
      };
      btn.textContent = labels[data.status] || data.status;
      if (data.status === "downloaded" && window.reloadLibrary) {
        // The processor ingests the PDF in the background; refresh the library list a few times.
        [15000, 45000, 90000].forEach((t) => setTimeout(window.reloadLibrary, t));
      }
      if (data.status === "failed" || data.status === "no_pdf") btn.disabled = false;
    } catch (e) {
      btn.textContent = "Error";
      btn.disabled = false;
    }
  };

  $("btn-discover-search").addEventListener("click", search);
  $("btn-discover-selection").addEventListener("click", fromSelection);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });
  const tab = $("tab-discover");
  if (tab) tab.addEventListener("click", () => { showTab(); input.focus(); });
})();
