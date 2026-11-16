// project-store.js — where project files (draft.tex, references.bib) live.
//  * server mode: the research-assistant API (projects/<name>/ on the computer)
//  * browser mode: localStorage, when the page runs without a server (e.g. on a
//    phone from GitHub Pages); Google Drive sync (drive-sync.js) moves projects
//    between the two.
// Both expose the same async API and a snapshot()/applySnapshot() pair used by sync.
(function () {
  "use strict";

  const LOCAL_KEY = "ra-projects";
  const TOMBSTONES_KEY = "ra-deleted-projects";
  const FILE_KEYS = { draft: "draft", bib: "bib" };
  const PROTECTED = new Set(["default"]);
  const DEFAULT_DRAFT = (name) =>
    `% Project: ${name}\n\\documentclass{article}\n\\begin{document}\n\n` +
    `\\bibliographystyle{plain}\n\\bibliography{references}\n\\end{document}\n`;

  function readJSON(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }
  function writeJSON(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
  }

  // Tombstones are shared by both modes: deleting a project anywhere must not let
  // sync bring it back.
  function getTombstones() {
    return readJSON(TOMBSTONES_KEY, {});
  }
  function addTombstone(name) {
    const t = getTombstones();
    t[name] = Date.now();
    writeJSON(TOMBSTONES_KEY, t);
  }
  function clearTombstone(name) {
    const t = getTombstones();
    if (name in t) {
      delete t[name];
      writeJSON(TOMBSTONES_KEY, t);
    }
  }
  function setTombstones(t) {
    writeJSON(TOMBSTONES_KEY, t || {});
  }

  function sanitize(name) {
    const safe = String(name || "").replace(/[^\p{L}\p{N}\-_. ]/gu, "").trim();
    if (!safe || safe.startsWith(".")) throw new Error("Invalid project name.");
    return safe;
  }

  // ---------------------------------------------------------------- browser
  const LocalBackend = {
    mode: "browser",
    _all() {
      return readJSON(LOCAL_KEY, {});
    },
    _save(all) {
      writeJSON(LOCAL_KEY, all);
    },
    async list() {
      const all = this._all();
      if (!Object.keys(all).length) {
        await this.create("default");
        return ["default"];
      }
      return Object.keys(all).sort();
    },
    async create(name) {
      name = sanitize(name);
      const all = this._all();
      if (all[name]) return { name, existed: true };
      const now = Date.now();
      all[name] = { draft: { content: DEFAULT_DRAFT(name), updatedAt: now }, bib: { content: "", updatedAt: now } };
      this._save(all);
      clearTombstone(name);
      return { name };
    },
    async remove(name) {
      if (PROTECTED.has(name)) throw new Error(`The '${name}' project cannot be deleted.`);
      const all = this._all();
      delete all[name];
      this._save(all);
      addTombstone(name);
    },
    async read(name, file) {
      const p = this._all()[name];
      if (!p) throw new Error(`Project '${name}' not found.`);
      const f = p[FILE_KEYS[file]] || { content: "", updatedAt: 0 };
      return { content: f.content || "", updatedAt: f.updatedAt || 0 };
    },
    async write(name, file, content, updatedAt) {
      const all = this._all();
      if (!all[name]) all[name] = {};
      all[name][FILE_KEYS[file]] = { content, updatedAt: updatedAt || Date.now() };
      this._save(all);
      return { updatedAt: all[name][FILE_KEYS[file]].updatedAt };
    },
    async snapshot() {
      return { app: "research-assistant", version: 1, projects: this._all(), deleted: getTombstones() };
    },
  };

  // ---------------------------------------------------------------- server
  function serverHeaders() {
    return {
      "Content-Type": "application/json",
      "x-auth-token": (window.CONFIG && window.CONFIG.AUTH_TOKEN) || "",
    };
  }
  async function api(path, opts = {}) {
    const base = (window.CONFIG && window.CONFIG.API_BASE) || "";
    const res = await fetch(base + path, { ...opts, headers: { ...serverHeaders(), ...(opts.headers || {}) } });
    if (!res.ok) {
      let detail = "";
      try {
        detail = (await res.json()).detail || "";
      } catch (e) { /* not JSON */ }
      const err = new Error(detail || `${path} → ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }
  const enc = encodeURIComponent;

  const ServerBackend = {
    mode: "server",
    async list() {
      const data = await api("/api/projects");
      if (!data.projects || !data.projects.length) {
        await this.create("default");
        return ["default"];
      }
      return data.projects;
    },
    async create(name) {
      try {
        const r = await api("/api/projects", { method: "POST", body: JSON.stringify({ name }) });
        clearTombstone(r.name || name);
        return { name: r.name || name };
      } catch (e) {
        if (e.status === 409) return { name, existed: true };
        throw e;
      }
    },
    async remove(name) {
      await api(`/api/projects/${enc(name)}`, { method: "DELETE" });
      addTombstone(name);
    },
    async read(name, file) {
      const r = await api(`/api/projects/${enc(name)}/${file}`);
      return { content: r.content || "", updatedAt: r.updated_at || 0 };
    },
    async write(name, file, content, updatedAt) {
      const r = await api(`/api/projects/${enc(name)}/${file}`, {
        method: "PUT",
        body: JSON.stringify({ content, updated_at: updatedAt || null }),
      });
      return { updatedAt: r.updated_at || Date.now() };
    },
    async snapshot() {
      const data = await api("/api/projects");
      const projects = {};
      for (const name of data.projects || []) {
        projects[name] = {};
        for (const file of ["draft", "bib"]) projects[name][file] = await this.read(name, file);
      }
      return { app: "research-assistant", version: 1, projects, deleted: getTombstones() };
    },
  };

  // Apply a merged snapshot to a backend: create, update (keeping timestamps) and delete.
  async function applySnapshot(backend, merged) {
    const current = await backend.snapshot();
    const changed = [];
    for (const [name, files] of Object.entries(merged.projects || {})) {
      const have = current.projects[name];
      if (!have) {
        const created = await backend.create(name);
        if (created.name !== name) {
          // The name is not valid here (e.g. made by an older version): skip it
          console.warn("Sync skipped a project with an invalid name:", name);
          continue;
        }
        changed.push(name);
      }
      for (const file of ["draft", "bib"]) {
        const want = files[file];
        if (!want) continue;
        const cur = have && have[file];
        if (!cur || cur.content !== want.content) {
          await backend.write(name, file, want.content, want.updatedAt);
          if (!changed.includes(name)) changed.push(name);
        }
      }
    }
    for (const name of Object.keys(current.projects)) {
      if (!(name in (merged.projects || {})) && (merged.deleted || {})[name] && !PROTECTED.has(name)) {
        try {
          await backend.remove(name);
          changed.push(name);
        } catch (e) {
          console.warn("Sync could not delete project", name, e);
        }
      }
    }
    setTombstones(merged.deleted || {});
    return changed;
  }

  // Server present? (/health answers without a password)
  async function detectServer() {
    const base = (window.CONFIG && window.CONFIG.API_BASE) || "";
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 4000);
      const res = await fetch(base + "/health", { signal: ctrl.signal, cache: "no-store" });
      clearTimeout(timer);
      if (!res.ok) return false;
      const data = await res.json();
      return data && data.status === "ok";
    } catch (e) {
      return false;
    }
  }

  window.ProjectStore = {
    backend: ServerBackend,
    useServer() {
      this.backend = ServerBackend;
    },
    useBrowser() {
      this.backend = LocalBackend;
    },
    isBrowserMode() {
      return this.backend === LocalBackend;
    },
    list: (...a) => window.ProjectStore.backend.list(...a),
    create: (...a) => window.ProjectStore.backend.create(...a),
    remove: (...a) => window.ProjectStore.backend.remove(...a),
    read: (...a) => window.ProjectStore.backend.read(...a),
    write: (...a) => window.ProjectStore.backend.write(...a),
    snapshot: () => window.ProjectStore.backend.snapshot(),
    applySnapshot: (merged) => applySnapshot(window.ProjectStore.backend, merged),
    detectServer,
    PROTECTED,
  };
})();
