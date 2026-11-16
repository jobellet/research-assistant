// sync-merge.js — pure merge of two project snapshots (no DOM; also runs in Node for tests).
//
// Snapshot: { app, version, projects: { name: { draft: {content, updatedAt}, bib: {content, updatedAt} } },
//             deleted: { name: deletedAtMs } }
// Rules:
//  - each file keeps the version with the newest updatedAt;
//  - a deletion wins over versions older than the deletion (tombstones are kept 90 days);
//  - if the same file changed on BOTH sides since the last sync (lastSyncAt), the older
//    edit is not lost: it is returned in `conflicts` and saved as "<name> - conflict <date>".
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SyncMerge = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const FILES = ["draft", "bib"];
  const TOMBSTONE_TTL_MS = 90 * 24 * 3600 * 1000;

  function emptySnapshot() {
    return { app: "research-assistant", version: 1, projects: {}, deleted: {} };
  }

  function normalize(snap) {
    const s = snap && typeof snap === "object" ? snap : {};
    return { ...emptySnapshot(), ...s, projects: { ...(s.projects || {}) }, deleted: { ...(s.deleted || {}) } };
  }

  function newest(project) {
    return Math.max(0, ...FILES.map((f) => (project && project[f] && project[f].updatedAt) || 0));
  }

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function conflictName(name, ts, taken) {
    const d = new Date(ts);
    // Only characters allowed in project names (letters, digits, - _ . space)
    const base = `${name} - conflict ${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}${pad(d.getMinutes())}`;
    let candidate = base;
    let i = 2;
    while (taken.has(candidate)) candidate = `${base} ${i++}`;
    return candidate;
  }

  /**
   * Merge local and remote snapshots.
   * @returns {{ result: object, conflicts: Array<{project, file, name, content, updatedAt}> }}
   */
  function mergeSnapshots(localSnap, remoteSnap, lastSyncAt = 0, now = Date.now()) {
    const local = normalize(localSnap);
    const remote = normalize(remoteSnap);
    const result = emptySnapshot();
    const conflicts = [];
    const names = new Set([
      ...Object.keys(local.projects), ...Object.keys(remote.projects),
      ...Object.keys(local.deleted), ...Object.keys(remote.deleted),
    ]);

    for (const name of names) {
      const tomb = Math.max(local.deleted[name] || 0, remote.deleted[name] || 0);
      const lp = local.projects[name];
      const rp = remote.projects[name];
      const merged = {};
      for (const f of FILES) {
        const lf = lp && lp[f];
        const rf = rp && rp[f];
        if (!lf && !rf) continue;
        if (!lf || !rf) {
          merged[f] = { ...(lf || rf) };
          continue;
        }
        const lt = lf.updatedAt || 0;
        const rt = rf.updatedAt || 0;
        const winner = lt >= rt ? lf : rf;
        const loser = winner === lf ? rf : lf;
        merged[f] = { ...winner };
        if (lf.content !== rf.content && lastSyncAt && lt > lastSyncAt && rt > lastSyncAt && loser.content) {
          conflicts.push({ project: name, file: f, content: loser.content, updatedAt: loser.updatedAt || 0 });
        }
      }
      const hasFiles = Object.keys(merged).length > 0;
      if (tomb && (!hasFiles || tomb >= newest(merged))) {
        if (now - tomb < TOMBSTONE_TTL_MS) result.deleted[name] = tomb;
        continue;
      }
      if (hasFiles) result.projects[name] = merged;
    }

    // Keep conflicting edits as their own projects
    const taken = new Set(Object.keys(result.projects));
    for (const c of conflicts) {
      const cname = conflictName(c.project, c.updatedAt || now, taken);
      taken.add(cname);
      c.name = cname;
      const copy = { draft: { content: "", updatedAt: c.updatedAt }, bib: { content: "", updatedAt: c.updatedAt } };
      copy[c.file] = { content: c.content, updatedAt: c.updatedAt };
      const original = result.projects[c.project] || {};
      const other = c.file === "draft" ? "bib" : "draft";
      if (original[other]) copy[other] = { ...original[other] };
      result.projects[cname] = copy;
    }
    return { result, conflicts };
  }

  /** True when two snapshots hold the same projects, files and tombstones. */
  function sameSnapshot(a, b) {
    const x = normalize(a);
    const y = normalize(b);
    const keys = (o) => Object.keys(o).sort().join("\u0000");
    if (keys(x.projects) !== keys(y.projects) || keys(x.deleted) !== keys(y.deleted)) return false;
    for (const name of Object.keys(x.projects)) {
      for (const f of FILES) {
        const p = x.projects[name][f];
        const q = y.projects[name][f];
        if (!!p !== !!q) return false;
        if (p && (p.content !== q.content || (p.updatedAt || 0) !== (q.updatedAt || 0))) return false;
      }
    }
    return Object.keys(x.deleted).every((n) => x.deleted[n] === y.deleted[n]);
  }

  return { mergeSnapshots, sameSnapshot, emptySnapshot, FILES };
});
