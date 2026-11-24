// Project references: link a Zotero collection to the active project, show which
// papers belong to the project, scope the library/search/graph to them, and find
// the sentences of those papers that match the claim highlighted in the draft.
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const api = async (path, opts = {}) => {
    const res = await fetch(`${CONFIG.API_BASE}${path}`, { ...opts, headers: authHeaders() });
    let body = null;
    try { body = await res.json(); } catch (e) { /* empty */ }
    if (!res.ok) throw new Error((body && body.detail) || `Request failed (${res.status})`);
    return body;
  };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = encodeURIComponent;

  const ui = {
    project: null,
    refs: null,          // last /refs response
    pollTimer: null,
    autoSyncTimer: null,
    lastClaim: "",
    evidenceSeq: 0,      // bumped for each evidence request and on project change
    renderGen: 0,        // bumped each time the evidence panel is rebuilt
    judgeGroups: [],
    aiEnabled: false,
    aiCheck: null,       // pending/settled /api/ai/settings check (null = not checked yet)
  };

  // Library scope: "project" or "all" (remembered per browser)
  function getScope() {
    try { return localStorage.getItem("libraryScope") || "project"; } catch (e) { return "project"; }
  }
  function setScope(v) {
    try { localStorage.setItem("libraryScope", v); } catch (e) { /* private mode */ }
  }
  function projectHasPapers() {
    return !!(ui.refs && ui.refs.papers && ui.refs.papers.length);
  }
  // The project whose papers scope library, search and graph (null = whole library)
  function scopedProject() {
    return state.serverMode && projectHasPapers() && getScope() === "project" ? ui.project : null;
  }

  // ------------------------------------------------------------------ summary
  function renderSummary() {
    const summary = $("refs-summary");
    const syncBtn = $("btn-refs-sync");
    const linkBtn = $("btn-refs-link");
    const r = ui.refs;
    if (!summary) return;
    if (!r) { summary.textContent = "…"; return; }
    const papers = r.papers || [];
    const indexed = papers.filter((p) => p.indexed).length;
    const z = r.zotero;
    const job = r.job || {};
    let html = "";
    if (z) {
      html += `Zotero: <strong>${esc(z.collection_name)}</strong>${z.include_subcollections ? " (+ subcollections)" : ""}<br>`;
    }
    html += papers.length
      ? `${papers.length} paper${papers.length > 1 ? "s" : ""}` +
        (indexed < papers.length ? ` · ${indexed} ready for sentence search` : " · all ready for sentence search")
      : "No papers in this project yet.";
    if (r.missing_pdf && r.missing_pdf.length) {
      const names = r.missing_pdf.map((m) => m.title || m.zotero_key).slice(0, 3).map(esc).join("; ");
      html += `<br><span title="${esc(r.missing_pdf.map((m) => m.title).join("\n"))}">${r.missing_pdf.length} without PDF in Zotero: ${names}${r.missing_pdf.length > 3 ? "…" : ""}</span>`;
    }
    if (job.running) {
      const what = job.kind === "sync" ? "Syncing with Zotero" : "Indexing sentences";
      const pct = job.total ? ` ${job.done}/${job.total}` : "";
      html += `<br><span class="refs-busy">⏳ ${what}${pct}${job.current && job.current !== "done" ? ": " + esc(String(job.current).slice(0, 60)) : ""}</span>`;
    } else if (job.error) {
      html += `<br><span style="color:#f87171">Last sync failed: ${esc(job.error)}</span>`;
    } else if (job.result && job.result.errors && job.result.errors.length) {
      html += `<br><span style="color:#f87171">${job.result.errors.length} item(s) could not be added</span>`;
    }
    if (z && z.last_sync && !job.running) {
      html += `<br><span style="opacity:.75">Synced ${new Date(z.last_sync * 1000).toLocaleString()}</span>`;
    }
    summary.innerHTML = html;
    if (syncBtn) syncBtn.hidden = !z;
    if (linkBtn) linkBtn.textContent = z ? "Change collection…" : "Link Zotero collection…";
    const listBtn = $("btn-refs-list");
    if (listBtn) listBtn.hidden = !papers.length;
    const scope = $("library-scope");
    if (scope) {
      scope.hidden = !papers.length;
      $("scope-project").textContent = `This project (${papers.length})`;
      $("scope-project").setAttribute("aria-pressed", String(getScope() === "project"));
      $("scope-all").setAttribute("aria-pressed", String(getScope() !== "project"));
    }
  }

  async function refresh() {
    if (!state.serverMode || !ui.project) return;
    const project = ui.project;
    try {
      const r = await api(`/api/projects/${enc(project)}/refs`);
      if (project !== ui.project) return;
      const wasRunning = ui.refs && ui.refs.job && ui.refs.job.running;
      const hadPapers = ui.refs ? (ui.refs.papers || []).map((p) => p.hash_id).join() : null;
      ui.refs = r;
      renderSummary();
      clearTimeout(ui.pollTimer);
      if (r.job && r.job.running) {
        ui.pollTimer = setTimeout(refresh, 2000);
      } else if (wasRunning) {
        if (r.job && r.job.result && r.job.result.added && r.job.result.added.length) {
          showToast(`${r.job.result.added.length} paper(s) added from Zotero.`, 4000);
        }
        if (ui.lastClaim) findEvidence(ui.lastClaim, true);   // now with the new index
      }
      const nowPapers = (r.papers || []).map((p) => p.hash_id).join();
      if (hadPapers !== null && hadPapers !== nowPapers && getScope() === "project") reloadScopedViews();
    } catch (e) {
      console.error("refs:", e);
      $("refs-summary").textContent = "Could not load the project's references.";
    }
  }

  function reloadScopedViews() {
    if (typeof loadLibrary === "function") loadLibrary();
    if (state.view === "graph" && typeof loadGraph === "function") loadGraph();
  }

  // After the user changes the scope, the paper matches of the selected claim are
  // fetched again in the new scope (re-selecting the same text would be a no-op).
  function rerunMatches() {
    if (!state.lastSelection || typeof performSemanticSearch !== "function") return;
    state.lastSearchedText = state.lastSelection;
    performSemanticSearch(state.lastSelection);
  }

  function changeScope(v) {
    setScope(v);
    renderSummary();
    reloadScopedViews();
    rerunMatches();
  }

  // ------------------------------------------------------------------ linking
  async function openLinkPanel() {
    const panel = $("refs-link-panel");
    const select = $("refs-collection-select");
    panel.classList.remove("hidden");
    select.innerHTML = "<option>Loading Zotero collections…</option>";
    select.disabled = true;
    $("btn-refs-unlink").hidden = !(ui.refs && ui.refs.zotero);
    try {
      const { collections } = await api("/api/zotero/collections");
      if (!collections.length) {
        select.innerHTML = "<option value=''>No collections in Zotero</option>";
        return;
      }
      const current = ui.refs && ui.refs.zotero ? ui.refs.zotero.collection_key : null;
      let lastLib = null;
      select.innerHTML = collections.map((c) => {
        const head = c.library !== lastLib && collections.some((x) => x.library !== "My Library")
          ? `<option disabled>── ${esc(c.library)} ──</option>` : "";
        lastLib = c.library;
        return head + `<option value="${esc(c.key)}" ${c.key === current ? "selected" : ""}>${esc(c.path)} (${c.item_count})</option>`;
      }).join("");
      select.disabled = false;
      if (ui.refs && ui.refs.zotero) $("refs-include-sub").checked = !!ui.refs.zotero.include_subcollections;
      select.focus();
    } catch (e) {
      select.innerHTML = `<option value=''>${esc(e.message)}</option>`;
    }
  }

  async function linkCollection() {
    const key = $("refs-collection-select").value;
    if (!key) return;
    const btn = $("btn-refs-link-ok");
    btn.disabled = true;
    try {
      await api(`/api/projects/${enc(ui.project)}/zotero`, {
        method: "PUT",
        body: JSON.stringify({ collection_key: key, include_subcollections: $("refs-include-sub").checked }),
      });
      $("refs-link-panel").classList.add("hidden");
      showToast("Linked. Copying the PDFs and indexing their sentences runs in the background.", 5000);
      setScope("project");
      await refresh();
    } catch (e) {
      showToast(e.message, 5000);
    } finally {
      btn.disabled = false;
    }
  }

  async function unlinkCollection() {
    if (!window.confirm("Unlink the Zotero collection? The papers stay in this project; new Zotero items will no longer be added.")) return;
    try {
      await api(`/api/projects/${enc(ui.project)}/zotero`, { method: "DELETE" });
      $("refs-link-panel").classList.add("hidden");
      await refresh();
    } catch (e) { showToast(e.message, 5000); }
  }

  async function syncNow(silent) {
    if (!ui.refs || !ui.refs.zotero) return;
    try {
      await api(`/api/projects/${enc(ui.project)}/sync`, { method: "POST" });
      await refresh();
    } catch (e) {
      if (!silent) showToast(e.message, 5000);
    }
  }

  // ------------------------------------------------------------------ evidence
  function highlightTerms(sentence, claim) {
    // Mark the sentence; underline words it shares with the claim.
    const words = new Set((claim.toLowerCase().match(/[a-z][a-z-]{3,}/g) || []));
    return esc(sentence).replace(/[A-Za-z][A-Za-z-]{3,}/g, (w) =>
      words.has(w.toLowerCase()) ? `<u>${w}</u>` : w);
  }

  const VERDICT = {
    supports: ["✓ supports", "#10b981"],
    partly: ["◐ partly", "#f59e0b"],
    contradicts: ["✗ contradicts", "#f87171"],
    unrelated: ["– unrelated", "#94a3b8"],
  };

  function passageHtml(p, s, claim, groupIdx, passIdx) {
    const pct = s.similarity != null ? Math.round(s.similarity * 100) + "% similar" : "word match";
    return `<div class="evidence-passage" data-group="${groupIdx}" data-pass="${passIdx}">` +
      (s.before ? `<span>${esc(s.before)} </span>` : "") +
      `<mark>${highlightTerms(s.text, claim)}</mark>` +
      (s.after ? `<span> ${esc(s.after)}</span>` : "") +
      `<div class="evidence-verdict" hidden></div>` +
      `<div class="evidence-foot"><span class="score-badge">${pct}</span><span>` +
      (s.page ? `<button class="view-btn" data-pdf="${esc(p.hash_id)}" data-page="${s.page}">PDF p. ${s.page}</button> ` : "") +
      `<button class="view-btn" data-copy="${esc(s.text)}" title="Copy the sentence">Copy</button>` +
      (p.bib_key ? ` <button class="view-btn" data-cite="${esc(p.bib_key)}" title="Copy \\cite{${esc(p.bib_key)}}">\\cite</button>` : "") +
      `</span></div></div>`;
  }

  // One block: a claim (whole selection or one cited part) and its papers' passages.
  function blockHtml(block, claim, groupIdx, opts) {
    const papers = (block.papers || []).filter((p) => p.passages && p.passages.length);
    const cited = papers.filter((p) => p.cited);
    const others = papers.filter((p) => !p.cited);
    let html = "";
    const paperHtml = (p) => {
      const meta = [p.authors, p.year].filter(Boolean).join(", ");
      let h = `<div class="evidence-paper"><div class="evidence-paper-title">` +
        (p.cited ? `<span class="cited-badge" title="Cited for this claim in your draft">cited</span> ` : "") +
        `${esc(p.title || p.hash_id)}` + (meta ? ` <span class="meta">(${esc(meta)})</span>` : "") +
        (p.method === "words" ? ` <span class="meta" title="The sentence index of this paper is still being built">· word match</span>` : "") +
        `</div>`;
      p.passages.forEach((s, k) => {
        ui.judgeGroups[groupIdx].passages.push({ hash_id: p.hash_id, title: p.title || "", text: s.text,
          before: s.before || "", after: s.after || "" });
        h += passageHtml(p, s, claim, groupIdx, ui.judgeGroups[groupIdx].passages.length - 1);
      });
      return h + `</div>`;
    };
    (block.unresolved || []).forEach((u) => {
      html += `<div class="evidence-note">Reference ${esc(u.label)} is not among this project's papers` +
        (u.reference ? `: <em>${esc(u.reference.slice(0, 140))}</em>` : "") + `.</div>`;
    });
    if (!papers.length) html += `<div class="evidence-note">No matching sentence in this project's papers.</div>`;
    cited.forEach((p) => { html += paperHtml(p); });
    if (others.length) {
      if (cited.length && opts.collapseOthers) {
        html += `<details class="evidence-others"><summary>${others.length} other paper(s) of the project</summary>`;
        others.forEach((p) => { html += paperHtml(p); });
        html += `</details>`;
      } else {
        others.forEach((p) => { html += paperHtml(p); });
      }
    }
    return html;
  }

  function renderEvidence(data, claim) {
    const box = $("evidence-section");
    if (!box) return;
    box.hidden = false;
    ui.renderGen++;
    ui.judgeGroups = [];
    const parts = data.parts || [];
    let html = `<div class="evidence-head"><span>In this project's references</span>` +
      (ui.aiEnabled ? `<button class="view-btn" id="btn-evidence-judge" title="Ask your AI provider (⚙ Settings) whether each passage supports the claim. Sends the claim and the passages to that provider.">Check with AI</button>` : "") +
      `</div>`;
    if (parts.length) {
      html += `<div class="evidence-claim">${esc(data.claim || claim)}</div>`;
      parts.forEach((part, g) => {
        ui.judgeGroups.push({ claim: part.claim, passages: [] });
        html += `<div class="evidence-part"><div class="evidence-part-claim">“${esc(part.claim)}” ` +
          `<span class="meta">[${esc(part.cites)}]</span></div>` +
          blockHtml(part, part.claim, g, { collapseOthers: true }) + `</div>`;
      });
    } else {
      ui.judgeGroups.push({ claim: data.claim || claim, passages: [] });
      html += `<div class="evidence-claim">${esc(data.claim || claim)}</div>` +
        blockHtml(data, data.claim || claim, 0, { collapseOthers: !!(data.cited && data.cited.length) });
    }
    if (data.not_indexed && data.not_indexed.length) {
      html += `<div class="evidence-note">⏳ ${data.not_indexed.length} paper(s) are still being indexed; ` +
        `their results are word matches for now and will improve when indexing ends.</div>`;
    }
    html += `<div class="evidence-divider">Papers matching the claim</div>`;
    box.innerHTML = html;
  }

  async function judgeEvidence(btn) {
    btn.disabled = true;
    btn.textContent = "Checking…";
    const project = ui.project;
    const gen = ui.renderGen;                    // the panel these verdicts belong to
    const groups = ui.judgeGroups;
    const box = $("evidence-section");
    const stale = () => gen !== ui.renderGen || project !== ui.project;
    try {
      await Promise.all(groups.map(async (group, g) => {
        if (!group.passages.length) return;
        const r = await api(`/api/projects/${enc(project)}/evidence/judge`, {
          method: "POST", body: JSON.stringify({ claim: group.claim, passages: group.passages.slice(0, 12) }),
        });
        if (stale() || !box) return;               // panel rebuilt for another claim/project
        (r.verdicts || []).forEach((v) => {
          const el = box.querySelector(`.evidence-passage[data-group="${g}"][data-pass="${Number(v.i)}"] .evidence-verdict`);
          if (!el) return;
          const [label, color] = VERDICT[v.verdict] || [v.verdict, "#94a3b8"];
          el.hidden = false;
          el.innerHTML = `<strong style="color:${color}">${esc(label)}</strong> ${esc(v.reason)}`;
        });
      }));
      btn.textContent = "Checked ✓";
    } catch (e) {
      if (stale()) return;
      showToast(e.message, 6000);
      btn.textContent = "Check with AI";
      btn.disabled = false;
    }
  }

  function renderEvidenceMessage(msg) {
    const box = $("evidence-section");
    if (!box) return;
    box.hidden = false;
    ui.renderGen++;
    box.innerHTML = `<div class="evidence-head"><span>In this project's references</span></div>` +
      `<div class="evidence-note">${msg}</div><div class="evidence-divider">Papers matching the claim</div>`;
  }

  async function findEvidence(claim, quiet) {
    if (!state.serverMode || !projectHasPapers()) {
      const box = $("evidence-section");
      if (box) box.hidden = true;
      return;
    }
    ui.lastClaim = claim;
    const seq = ++ui.evidenceSeq;
    if (!quiet) renderEvidenceMessage("Searching the sentences of this project's papers…");
    try {
      const [data] = await Promise.all([
        api(`/api/projects/${enc(ui.project)}/evidence`, {
          method: "POST",
          body: JSON.stringify({ text: claim, per_paper: 4, top_k: 10 }),
        }),
        ensureAiChecked(),                         // decides whether "Check with AI" is shown
      ]);
      if (seq !== ui.evidenceSeq) return;          // a newer selection/project is being searched
      renderEvidence(data, claim);
      if (data.job && data.job.running) refresh();
    } catch (e) {
      if (seq === ui.evidenceSeq) renderEvidenceMessage(esc(e.message));
    }
  }

  function onEvidenceClick(e) {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.id === "btn-evidence-judge") { judgeEvidence(b); return; }
    if (b.dataset.pdf) {
      const url = `${CONFIG.API_BASE}/api/pdf/${enc(b.dataset.pdf)}?token=${enc(CONFIG.AUTH_TOKEN)}#page=${b.dataset.page}`;
      const frame = document.getElementById("pdf-frame");
      const modal = document.getElementById("pdf-modal");
      if (frame && modal) {
        frame.src = "about:blank";               // force reload so the page anchor is applied
        setTimeout(() => { frame.src = url; }, 30);
        modal.style.display = "flex";
      } else {
        window.open(url, "_blank");
      }
    } else if (b.dataset.copy || b.dataset.cite) {
      const text = b.dataset.cite ? `\\cite{${b.dataset.cite}}` : b.dataset.copy;
      navigator.clipboard.writeText(text).then(() => {
        const old = b.textContent;
        b.textContent = "Copied!";
        setTimeout(() => { b.textContent = old; }, 1200);
      }).catch(() => showToast("Copy failed", 2500));
    }
  }

  // ------------------------------------------------------------------ docx import
  async function importDocx(file) {
    if (!file) return;
    if (!/\.docx$/i.test(file.name)) { showToast("Choose a .docx file", 3000); return; }
    const project = ui.project;
    // Judge the overwrite on the draft itself, whichever tab is open.
    let current = "";
    if (state.activeFile === "draft") {
      current = editor.value || "";
    } else {
      try { current = (await window.ProjectStore.read(project, "draft")).content || ""; }
      catch (e) { current = "?"; }               // unknown content: ask before replacing
    }
    current = current.trim();
    if (current && !/^% (Default project draft|Project: )/.test(current) &&
        !window.confirm(`Replace the draft of "${project}" with the text of ${file.name}?`)) return;
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
    try {
      const r = await api(`/api/projects/${enc(project)}/import-docx`, {
        method: "POST", body: JSON.stringify({ filename: file.name, data_base64: data }),
      });
      if (project !== ui.project || project !== state.activeProject) return;   // project switched meanwhile
      await switchToDraft();
      if (state.activeFile !== "draft" || state.loadedFile !== `${project}/draft`) {
        showToast("Could not open the draft; nothing was imported.", 5000);
        return;
      }
      editor.value = r.text;
      editor.dispatchEvent(new Event("input"));
      showToast(`Imported ${r.paragraphs} paragraphs. Select a sentence to see the matching passages.`, 5000);
    } catch (e) {
      showToast(e.message, 5000);
    }
  }

  // Open the draft tab and wait until its content is in the editor (same steps as
  // a click on the tab in app.js, but awaited, so nothing can overwrite the import).
  async function switchToDraft() {
    if (state.activeFile === "draft" && state.loadedFile === `${state.activeProject}/draft`) return;
    if (state.saveTimer) clearTimeout(state.saveTimer);
    if (saveStatus.textContent === "Unsaved") await saveCurrentFile(true);
    document.querySelectorAll("#file-list .nav-item[data-file]").forEach((i) =>
      i.classList.toggle("active", i.dataset.file === "draft"));
    state.activeFile = "draft";
    await loadCurrentFile();
  }

  // ------------------------------------------------------------------ wiring
  function onProjectChanged(name) {
    if (name === ui.project && ui.refs) { refresh(); return; }   // same project reloaded (e.g. Drive sync)
    ui.project = name;
    ui.refs = null;
    ui.lastClaim = "";
    ui.evidenceSeq++;                              // drop evidence still in flight for the old project
    ui.renderGen++;                                // and AI verdicts for its panel
    ensureAiChecked();
    const box = $("evidence-section");
    if (box) { box.hidden = true; box.innerHTML = ""; }
    $("refs-link-panel") && $("refs-link-panel").classList.add("hidden");
    renderSummary();
    refresh().then(() => {
      // pick up items added to the Zotero collection since the last sync
      if (ui.refs && ui.refs.zotero && !(ui.refs.job && ui.refs.job.running)) syncNow(true);
      reloadScopedViews();
    });
  }

  function wire() {
    if (!$("refs-section")) return;
    $("btn-refs-link").addEventListener("click", openLinkPanel);
    $("btn-refs-link-cancel").addEventListener("click", () => $("refs-link-panel").classList.add("hidden"));
    $("btn-refs-link-ok").addEventListener("click", linkCollection);
    $("btn-refs-unlink").addEventListener("click", unlinkCollection);
    $("btn-refs-sync").addEventListener("click", () => syncNow(false));
    $("btn-refs-list").addEventListener("click", () => {
      if (typeof switchSidePanel === "function") switchSidePanel("library");
      changeScope("project");
    });
    $("scope-project").addEventListener("click", () => changeScope("project"));
    $("scope-all").addEventListener("click", () => changeScope("all"));
    $("evidence-section").addEventListener("click", onEvidenceClick);
    const input = $("docx-file-input");
    const importItem = $("btn-import-docx");
    if (importItem && input) {
      const open = () => { input.value = ""; input.click(); };
      importItem.addEventListener("click", open);
      importItem.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
      input.addEventListener("change", () => importDocx(input.files[0]));
    }
    // New Zotero items are picked up every 5 minutes while the page is open.
    ui.autoSyncTimer = setInterval(() => {
      if (document.visibilityState === "visible") syncNow(true);
    }, 5 * 60 * 1000);
  }

  // Whether an AI provider is configured. Checked lazily (state.serverMode is not
  // known yet when this script starts) and again when the AI settings are saved.
  function checkAi() {
    ui.aiCheck = api("/api/ai/settings")
      .then((s) => { ui.aiEnabled = !!(s && s.enabled); })
      .catch(() => { ui.aiEnabled = false; });
    return ui.aiCheck;
  }
  function ensureAiChecked() {
    if (!state.serverMode) return Promise.resolve();
    return ui.aiCheck || checkAi();
  }

  window.ProjectRefsUI = { onProjectChanged, findEvidence, scopedProject, refresh, checkAi };

  function start() {
    wire();
    window.addEventListener("ai-settings-changed", () => {
      if (!state.serverMode) return;
      const before = ui.aiEnabled;
      checkAi().then(() => {
        if (ui.aiEnabled !== before && ui.lastClaim) findEvidence(ui.lastClaim, true);
      });
    });
    // app.js may have opened a project before this script was loaded
    if (state.serverMode && state.activeProject && !ui.project) onProjectChanged(state.activeProject);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
