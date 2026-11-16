// phone-library.js — the library without a server (browser mode, e.g. on a phone).
// Uses the library index that a computer running the server copies to Google Drive
// (drive-sync.js), and JavaScript ports of the Python helpers (literature-core.js):
// browse + filter + word search, read abstracts, open the paper online, cite into the
// project's references.bib, search OpenAlex/Crossref, and queue "add to library"
// requests that the computer carries out at its next sync.
(function () {
  "use strict";
  const L = window.LiteratureCore;
  const PENDING_KEY = "ra-inbox-pending";
  const REQUESTS_KEY = "ra-inbox-requests";
  let index = { papers: [] };

  // ---- tiny IndexedDB store (the index can exceed localStorage limits)
  function idb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open("research-assistant", 1);
      req.onupgradeneeded = () => req.result.createObjectStore("kv");
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function idbGet(key) {
    const db = await idb();
    return new Promise((resolve) => {
      const r = db.transaction("kv").objectStore("kv").get(key);
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => resolve(undefined);
    });
  }
  async function idbSet(key, value) {
    const db = await idb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction("kv", "readwrite");
      tx.objectStore("kv").put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  function toLibraryItem(p) {
    return {
      hash_id: p.hash_id,
      metadata: {
        title: p.title, authors: (p.authors || []).join(", "), year: p.year, journal: p.journal,
        doi: p.doi, keywords: (p.keywords || []).join(", "), pdf_filename: "",
      },
      files: p.arxiv_id || p.doi ? [{ filename: "online" }] : [],
    };
  }
  const byHash = (h) => (index.papers || []).find((p) => p.hash_id === h);
  const onlineUrl = (p) => (p.arxiv_id ? `https://arxiv.org/pdf/${p.arxiv_id}` : p.doi ? `https://doi.org/${p.doi}` : "");

  async function setIndex(data) {
    index = data && Array.isArray(data.papers) ? data : { papers: [] };
    try {
      await idbSet("library-index", index);
    } catch (e) {
      console.warn("Could not store the library index", e);
    }
    render();
  }

  function render() {
    const st = window.appState;
    if (!st) return;
    st.libraryData = (index.papers || []).map(toLibraryItem);
    if (!st.libraryData.length) return; // keep the "needs the server / sync" note
    if (typeof renderLibrary === "function") renderLibrary(st.libraryData);
  }

  // Word search for the Library tab (replaces the server's semantic / word-frequency search)
  function search(query) {
    return L.wordSearch(index.papers || [], query, 50).map((h) => ({ ...toLibraryItem(h.paper), score: h.score }));
  }

  // ---- overrides of server-backed buttons in browser mode
  function installOverrides() {
    window.openPDF = (hash) => {
      const p = byHash(hash);
      const url = p && onlineUrl(p);
      if (url) window.open(url, "_blank", "noopener");
    };
    window.openRawText = (hash, title) => {
      const p = byHash(hash) || {};
      const modal = document.getElementById("text-modal");
      document.getElementById("text-modal-title").textContent = title || p.title || "";
      document.getElementById("text-modal-body").textContent =
        [p.title, (p.authors || []).join(", "), [p.journal, p.year].filter(Boolean).join(", "),
          p.doi ? `doi:${p.doi}` : "", "", p.summary || "(no abstract)",
          "", "The full text is available on your computer."].filter((x) => x !== undefined).join("\n");
      modal.style.display = "flex";
    };
    window.openQuickGraph = () => {};
    window.addToBib = async (hash) => {
      const p = byHash(hash);
      const st = window.appState;
      if (!p || !st || !st.activeProject) return;
      const btns = [document.getElementById(`bib-btn-${hash}`), document.getElementById(`bib-btn-lib-${hash}`)].filter(Boolean);
      const bib = await window.ProjectStore.read(st.activeProject, "bib");
      const r = L.addToBib(bib.content, p);
      if (r.added) await window.ProjectStore.write(st.activeProject, "bib", r.content);
      if (st.activeFile === "bib" && typeof loadCurrentFile === "function") await loadCurrentFile();
      if (window.DriveSync) window.DriveSync.notifyLocalChange();
      btns.forEach((b) => { b.textContent = `\\cite{${r.key}}`; });
      try { await navigator.clipboard.writeText(`\\cite{${r.key}}`); } catch (e) { /* optional */ }
    };
  }

  // ---- online search (OpenAlex + Crossref allow browser requests; arXiv does not)
  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${new URL(url).host} ${r.status}`);
    return r.json();
  }
  async function openalexSearch(q, n = 20) {
    const d = await getJSON(`https://api.openalex.org/works?search=${encodeURIComponent(q)}&per-page=${Math.min(n, 50)}`);
    return (d.results || []).map((w) => L.parseOpenAlex(w));
  }
  async function crossrefSearch(q, n = 20) {
    const d = await getJSON(`https://api.crossref.org/works?query=${encodeURIComponent(q)}&rows=${n}`);
    return ((d.message || {}).items || []).map((i) => L.parseCrossref(i)).filter((c) => c.title);
  }
  async function openalexRelated(p, n = 20) {
    const doi = p.doi || (p.arxiv_id ? `10.48550/arXiv.${p.arxiv_id}` : "");
    if (!doi) return [];
    const seed = await getJSON(`https://api.openalex.org/works/doi:${encodeURIComponent(doi)}`);
    const ids = (seed.related_works || []).map((r) => r.split("/").pop()).slice(0, n);
    if (!ids.length) return [];
    const d = await getJSON(`https://api.openalex.org/works?filter=openalex:${ids.join("|")}&per-page=${n}`);
    return (d.results || []).map((w) => L.parseOpenAlex(w, "openalex_related"));
  }
  async function settled(jobs) {
    const names = Object.keys(jobs);
    const res = await Promise.allSettled(names.map((k) => jobs[k]()));
    const out = {};
    names.forEach((k, i) => { out[k] = res[i].status === "fulfilled" ? res[i].value : []; });
    return out;
  }
  function annotate(results) {
    return results.map((c) => {
      const h = L.matchLibrary(c, index.papers);
      return { ...c, in_library: Boolean(h), hash_id: h, downloadable: Boolean(c.pdf_url || c.arxiv_id) };
    });
  }
  async function discover(kind, arg, limit = 20) {
    let raw;
    let extra = {};
    if (kind === "search") {
      const sources = (arg.sources || []).filter((s) => s === "openalex" || s === "crossref");
      const jobs = {};
      if (!sources.length || sources.includes("openalex")) jobs.openalex = () => openalexSearch(arg.query, limit);
      if (sources.includes("crossref")) jobs.crossref = () => crossrefSearch(arg.query, limit);
      raw = await settled(jobs);
    } else if (kind === "text") {
      const terms = L.extractQueryTerms(arg.text);
      extra = { terms, query: terms.join(" ") };
      raw = await settled({ openalex: () => openalexSearch(terms.join(" "), limit) });
    } else {
      const p = byHash(arg.hash) || {};
      extra = { seed: { title: p.title, doi: p.doi, arxiv_id: p.arxiv_id } };
      const terms = L.extractQueryTerms(`${p.title || ""} ${(p.keywords || []).join(" ")}`, 4);
      raw = await settled({
        openalex_related: () => openalexRelated(p, limit),
        openalex: () => (terms.length ? openalexSearch(terms.join(" "), limit) : Promise.resolve([])),
      });
    }
    const merged = L.mergeRanked(Object.values(raw))
      .filter((c) => !extra.seed || L.normTitle(c.title) !== L.normTitle(extra.seed.title)).slice(0, limit);
    const per = {};
    Object.entries(raw).forEach(([k, v]) => { per[k] = v.length; });
    return { results: annotate(merged), per_source: per, ...extra };
  }

  // ---- "add to library" requests, carried out by the computer at its next sync
  function readList(key) {
    try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch (e) { return []; }
  }
  function queueAdd(candidate) {
    const key = candidate.arxiv_id ? `arxiv:${candidate.arxiv_id}` : candidate.doi ? `doi:${candidate.doi.toLowerCase()}` : `title:${L.normTitle(candidate.title)}`;
    const pending = readList(PENDING_KEY);
    if (!pending.some((r) => r.key === key)) {
      pending.push({
        key, status: "pending", addedAt: Date.now(),
        identifier: candidate.arxiv_id || candidate.doi || "",
        candidate: { title: candidate.title, authors: candidate.authors, year: candidate.year, doi: candidate.doi,
          arxiv_id: candidate.arxiv_id, pdf_url: candidate.pdf_url, source: candidate.source },
      });
      localStorage.setItem(PENDING_KEY, JSON.stringify(pending));
    }
    if (window.DriveSync) window.DriveSync.notifyLocalChange();
    return { status: "queued" };
  }
  function pendingRequests() {
    return readList(PENDING_KEY);
  }
  function requestsSent(all) {
    localStorage.setItem(PENDING_KEY, "[]");
    localStorage.setItem(REQUESTS_KEY, JSON.stringify(all || []));
  }

  async function init() {
    installOverrides();
    try {
      const stored = await idbGet("library-index");
      if (stored) index = stored;
    } catch (e) { /* first use */ }
    render();
    window.addEventListener("libraryIndexSynced", render);
  }

  window.PhoneLibrary = { init, setIndex, search, discover, queueAdd, pendingRequests, requestsSent,
    count: () => (index.papers || []).length };
})();
