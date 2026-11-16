// ask.js — "Ask" tab: a question answered from the user's own library.
// 1) semantic search picks the most relevant papers, 2) the configured AI provider
// (Settings → AI provider) answers using only those papers and cites them as [n].
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const input = $("ask-input");
  const results = $("ask-results");
  const statusEl = $("ask-status");
  if (!input || !results) return;
  const N_PAPERS = 8;

  const headers = () => ({
    "Content-Type": "application/json",
    "x-auth-token": (window.CONFIG && window.CONFIG.AUTH_TOKEN) || "",
  });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);

  function setStatus(msg) {
    statusEl.textContent = msg || "";
  }

  // Minimal safe formatting: paragraphs, **bold**, and [n] links to the sources.
  function format(text, n) {
    return esc(text)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/\[(\d+(?:\s*[,–-]\s*\d+)*)\]/g, (m, refs) =>
        refs.split(/\s*,\s*/).map((r) => {
          const k = parseInt(r, 10);
          return k >= 1 && k <= n ? `<a href="#ask-src-${k}" class="ask-ref">[${esc(r)}]</a>` : `[${esc(r)}]`;
        }).join(""))
      .split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
  }

  function sourceCard(p, i) {
    const m = p.metadata || {};
    const authors = String(m.authors || "").split(",").slice(0, 2).join(",") +
      (String(m.authors || "").split(",").length > 2 ? " et al." : "");
    return `<div class="result-card" id="ask-src-${i + 1}" style="padding:0.75rem;margin-bottom:0.5rem">
      <div class="result-title" style="font-size:0.85rem">[${i + 1}] ${esc(m.title || "Untitled")}</div>
      <div class="discover-meta">${esc(authors)} ${m.year ? "(" + esc(m.year) + ")" : ""}</div>
      <div class="result-footer" style="justify-content:flex-end">
        <div style="display:flex;gap:0.3rem">
          <button class="view-btn" onclick="openRawText('${esc(p.hash_id)}', 'Paper ${i + 1}')">Text</button>
          <button class="view-btn" onclick="openPDF('${esc(p.hash_id)}')">PDF</button>
          <button class="view-btn" style="background:#3b82f6" onclick="askCite('${esc(p.hash_id)}', this)">Cite</button>
        </div>
      </div></div>`;
  }

  window.askCite = async (hashId, btn) => {
    btn.disabled = true;
    try {
      const project = (window.appState && window.appState.activeProject) || "default";
      const r = await fetch("/api/citation/add", {
        method: "POST", headers: headers(), body: JSON.stringify({ hash_id: hashId, project }),
      });
      const d = await r.json();
      btn.textContent = r.ok ? `\\cite{${d.bib_key}}` : "Error";
      if (r.ok) {
        try { await navigator.clipboard.writeText(`\\cite{${d.bib_key}}`); } catch (e) { /* optional */ }
      }
    } finally {
      btn.disabled = false;
    }
  };

  async function ask(question) {
    question = (question || "").trim();
    if (question.length < 5) {
      setStatus("Type a question first.");
      return;
    }
    if (window.switchSidePanel) window.switchSidePanel("ask");
    setStatus("Finding the most relevant papers…");
    results.innerHTML = "";
    let papers = [];
    try {
      const r = await fetch("/api/search", {
        method: "POST", headers: headers(),
        body: JSON.stringify({ query: question, n_results: N_PAPERS, method: "semantic" }),
      });
      if (!r.ok) throw new Error(`search failed (${r.status})`);
      papers = await r.json();
    } catch (e) {
      setStatus("Search failed: " + e.message);
      return;
    }
    if (!papers.length) {
      setStatus("No papers in the library match this question.");
      return;
    }
    const context = papers.map((p) => ({
      title: (p.metadata || {}).title, authors: (p.metadata || {}).authors,
      year: (p.metadata || {}).year, summary: p.summary || "",
    }));
    results.innerHTML = `<div class="ask-answer" id="ask-answer"></div>
      <div class="discover-meta" style="margin:0.75rem 0 0.5rem">Sources</div>
      ${papers.map(sourceCard).join("")}`;
    const answerEl = $("ask-answer");
    setStatus(`Answering from ${papers.length} papers…`);
    let text = "";
    try {
      const r = await fetch("/api/chat", {
        method: "POST", headers: headers(),
        body: JSON.stringify({ query: question, context_papers: context }),
      });
      if (!r.ok || !r.body) throw new Error(`answer failed (${r.status})`);
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        text += dec.decode(value, { stream: true });
        answerEl.innerHTML = format(text, papers.length);
      }
      setStatus(`Answer based on ${papers.length} papers of your library — check the sources.`);
    } catch (e) {
      setStatus("Could not get an answer: " + e.message);
    }
  }

  $("btn-ask").addEventListener("click", () => ask(input.value));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(input.value);
  });
  $("btn-ask-selection").addEventListener("click", () => {
    const sel = (window.appState && window.appState.lastSelection) || "";
    if (!sel) {
      setStatus("Highlight a passage in the editor first.");
      return;
    }
    input.value = `What does my library say about this claim: "${sel}"`;
    ask(input.value);
  });
  const tab = $("tab-ask");
  if (tab) tab.addEventListener("click", () => {
    if (window.switchSidePanel) window.switchSidePanel("ask");
    input.focus();
  });
})();
