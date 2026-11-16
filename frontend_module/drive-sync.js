// drive-sync.js — sync projects (draft.tex + references.bib) between devices through a
// private Google Drive app folder (adapted from ADHDtools services/drive-sync.js).
// The app folder is hidden and only readable by this app. Three files live there:
//  - research-assistant-projects.json  projects (merged both ways)
//  - research-assistant-library.json   library index (metadata + abstracts), written by a
//                                      computer running the server, read by the phone
//  - research-assistant-inbox.json     "add to library" requests made on the phone, carried
//                                      out by the computer (downloads the PDF into its inbox)
// PDFs themselves are not copied: keep them in a Google Drive for Desktop folder (DATA_DIR).
(function () {
  "use strict";
  const SCOPE = "https://www.googleapis.com/auth/drive.appdata";
  const FILENAME = "research-assistant-projects.json";
  const LIBRARY_FILE = "research-assistant-library.json";
  const INBOX_FILE = "research-assistant-inbox.json";
  const LIB_VERSION_KEY = "ra-drive-library-version";
  const LIB_MODIFIED_KEY = "ra-drive-library-modified";
  const DRIVE_API = "https://www.googleapis.com/drive/v3";
  const DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3";
  const LAST_SYNC_KEY = "ra-drive-last-sync";
  const AUTO_KEY = "ra-drive-auto";
  const PUSH_DEBOUNCE_MS = 4000;
  const POLL_MS = 30000;

  let inFlight = null;
  let pushTimer = null;
  let pollTimer = null;
  let fileId = null;
  let lastError = "";

  const listeners = new Set();
  function emit() {
    listeners.forEach((fn) => {
      try { fn(status()); } catch (e) { /* ignore */ }
    });
  }

  function lastSyncAt() {
    return Number(localStorage.getItem(LAST_SYNC_KEY) || 0) || 0;
  }
  function autoSync() {
    return localStorage.getItem(AUTO_KEY) !== "false";
  }
  function setAutoSync(on) {
    localStorage.setItem(AUTO_KEY, on ? "true" : "false");
    if (on) start();
    emit();
  }
  function connected() {
    return window.GoogleAuth.hasSession(SCOPE);
  }
  function status() {
    return {
      configured: Boolean(window.GoogleAuth.getClientId()),
      connected: connected(),
      autoSync: autoSync(),
      lastSyncAt: lastSyncAt(),
      syncing: Boolean(inFlight),
      error: lastError,
    };
  }

  async function findNamed(token, name) {
    const url = new URL(`${DRIVE_API}/files`);
    url.searchParams.set("spaces", "appDataFolder");
    url.searchParams.set("q", `name = '${name}' and trashed = false`);
    url.searchParams.set("fields", "files(id, modifiedTime)");
    const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(`Google Drive error ${r.status}`);
    return ((await r.json()).files || [])[0] || null;
  }

  async function uploadNamed(token, name, obj, id) {
    const body = JSON.stringify(obj);
    if (id) {
      const r = await fetch(`${DRIVE_UPLOAD}/files/${id}?uploadType=media`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body,
      });
      if (!r.ok) throw new Error(`Google Drive error ${r.status}`);
      return id;
    }
    const boundary = "ra" + Date.now();
    const multipart =
      `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n` +
      JSON.stringify({ name, parents: ["appDataFolder"] }) +
      `\r\n--${boundary}\r\nContent-Type: application/json\r\n\r\n${body}\r\n--${boundary}--`;
    const r = await fetch(`${DRIVE_UPLOAD}/files?uploadType=multipart`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": `multipart/related; boundary=${boundary}` },
      body: multipart,
    });
    if (!r.ok) throw new Error(`Google Drive error ${r.status}`);
    return (await r.json()).id || null;
  }

  // ---- library index: computer → Drive → phone
  async function syncLibrary(token) {
    const store = window.ProjectStore;
    if (!store.isBrowserMode()) {
      const base = (window.CONFIG && window.CONFIG.API_BASE) || "";
      const r = await fetch(`${base}/api/library/export`, {
        headers: { "x-auth-token": (window.CONFIG && window.CONFIG.AUTH_TOKEN) || "" },
      });
      if (!r.ok) return;
      const index = await r.json();
      if (index.version === localStorage.getItem(LIB_VERSION_KEY)) return;
      const existing = await findNamed(token, LIBRARY_FILE);
      await uploadNamed(token, LIBRARY_FILE, { ...index, exportedAt: Date.now() }, existing && existing.id);
      localStorage.setItem(LIB_VERSION_KEY, index.version);
      return;
    }
    const remote = await findNamed(token, LIBRARY_FILE);
    if (!remote || remote.modifiedTime === localStorage.getItem(LIB_MODIFIED_KEY)) return;
    const index = await download(token, remote.id);
    if (window.PhoneLibrary) await window.PhoneLibrary.setIndex(index);
    localStorage.setItem(LIB_MODIFIED_KEY, remote.modifiedTime);
    window.dispatchEvent(new CustomEvent("libraryIndexSynced"));
  }

  // ---- "add to library" queue: phone → Drive → computer
  async function syncInbox(token) {
    const pending = window.PhoneLibrary ? window.PhoneLibrary.pendingRequests() : [];
    const isServer = !window.ProjectStore.isBrowserMode();
    if (!isServer && !pending.length) return;
    const file = await findNamed(token, INBOX_FILE);
    const queue = file ? await download(token, file.id) : { requests: [] };
    let changed = false;
    const known = new Set((queue.requests || []).map((q) => q.key));
    for (const req of pending) {
      if (!known.has(req.key)) {
        queue.requests.push(req);
        changed = true;
      }
    }
    if (isServer) {
      const base = (window.CONFIG && window.CONFIG.API_BASE) || "";
      for (const req of queue.requests) {
        if (req.status !== "pending") continue;
        try {
          const r = await fetch(`${base}/api/discover/fetch`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "x-auth-token": (window.CONFIG && window.CONFIG.AUTH_TOKEN) || "" },
            body: JSON.stringify(req.identifier ? { identifier: req.identifier } : { candidate: req.candidate }),
          });
          const d = await r.json();
          req.status = r.ok ? d.status : "failed";
        } catch (e) {
          req.status = "failed";
        }
        req.doneAt = Date.now();
        changed = true;
      }
      const month = 30 * 24 * 3600 * 1000;
      const before = queue.requests.length;
      queue.requests = queue.requests.filter((q) => q.status === "pending" || Date.now() - (q.doneAt || 0) < month);
      changed = changed || queue.requests.length !== before;
    }
    if (changed) await uploadNamed(token, INBOX_FILE, queue, file && file.id);
    if (window.PhoneLibrary) window.PhoneLibrary.requestsSent(queue.requests);
  }

  async function findFile(token) {
    const url = new URL(`${DRIVE_API}/files`);
    url.searchParams.set("spaces", "appDataFolder");
    url.searchParams.set("q", `name = '${FILENAME}' and trashed = false`);
    url.searchParams.set("fields", "files(id, modifiedTime)");
    const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(`Google Drive error ${r.status}`);
    const f = ((await r.json()).files || [])[0] || null;
    fileId = f ? f.id : null;
    return f;
  }

  async function download(token, id) {
    const r = await fetch(`${DRIVE_API}/files/${id}?alt=media`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(`Google Drive error ${r.status}`);
    return r.json();
  }

  async function upload(token, snapshot) {
    const body = JSON.stringify({ ...snapshot, exportedAt: Date.now() });
    if (fileId) {
      const r = await fetch(`${DRIVE_UPLOAD}/files/${fileId}?uploadType=media`, {
        method: "PATCH",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body,
      });
      if (!r.ok) throw new Error(`Google Drive error ${r.status}`);
      return;
    }
    const boundary = "ra" + Date.now();
    const multipart =
      `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n` +
      JSON.stringify({ name: FILENAME, parents: ["appDataFolder"] }) +
      `\r\n--${boundary}\r\nContent-Type: application/json\r\n\r\n${body}\r\n--${boundary}--`;
    const r = await fetch(`${DRIVE_UPLOAD}/files?uploadType=multipart`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": `multipart/related; boundary=${boundary}` },
      body: multipart,
    });
    if (!r.ok) throw new Error(`Google Drive error ${r.status}`);
    fileId = (await r.json()).id || null;
  }

  /**
   * Pull, merge and push. interactive=true may open the Google sign-in popup
   * (only call it from a click); automatic syncs never do.
   */
  function syncNow({ interactive = false } = {}) {
    if (inFlight) return inFlight;
    inFlight = (async () => {
      emit();
      try {
        const token = await window.GoogleAuth.getAccessToken(SCOPE, { interactive });
        if (!token) return { skipped: true };
        if (window.appBeforeSync) await window.appBeforeSync(); // save the open file first
        const remoteFile = await findFile(token);
        const remote = remoteFile ? await download(token, remoteFile.id) : null;
        const local = await window.ProjectStore.snapshot();
        const { result, conflicts } = window.SyncMerge.mergeSnapshots(local, remote, lastSyncAt());
        const changed = await window.ProjectStore.applySnapshot(result);
        // Upload what this device now has (timestamps may have been normalised by the server)
        const after = await window.ProjectStore.snapshot();
        if (!remote || !window.SyncMerge.sameSnapshot(after, remote)) await upload(token, after);
        try {
          await syncLibrary(token);
          await syncInbox(token);
        } catch (e) {
          console.warn("Library/inbox sync skipped:", e);
        }
        localStorage.setItem(LAST_SYNC_KEY, String(Date.now()));
        lastError = "";
        if (changed.length || conflicts.length) {
          window.dispatchEvent(new CustomEvent("projectsSynced", { detail: { changed, conflicts } }));
        }
        return { changed, conflicts };
      } catch (e) {
        lastError = e.message || String(e);
        console.warn("Drive sync failed:", e);
        if (interactive) throw e;
        return { error: lastError };
      } finally {
        inFlight = null;
        emit();
      }
    })();
    return inFlight;
  }

  // Called after every save: push a few seconds later (only when already signed in).
  function notifyLocalChange() {
    if (!autoSync() || !connected()) return;
    clearTimeout(pushTimer);
    pushTimer = setTimeout(() => syncNow(), PUSH_DEBOUNCE_MS);
  }

  function start() {
    if (pollTimer || !autoSync()) return;
    pollTimer = setInterval(() => {
      if (document.visibilityState === "visible" && autoSync() && connected()) syncNow();
    }, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible" && autoSync() && connected()) syncNow();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    window.addEventListener("online", onVisible);
    if (connected()) syncNow();
  }

  function disconnect() {
    window.GoogleAuth.signOut(SCOPE);
    lastError = "";
    emit();
  }

  window.DriveSync = {
    syncNow, notifyLocalChange, start, disconnect, status, setAutoSync,
    onChange: (fn) => listeners.add(fn),
    SCOPE,
  };
})();
