import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { mergeSnapshots, sameSnapshot } = require("../../frontend_module/sync-merge.js");

const file = (content, updatedAt) => ({ content, updatedAt });
const snap = (projects, deleted = {}) => ({ projects, deleted });
const NOW = Date.UTC(2026, 10, 16, 12, 0);

test("newest version of each file wins", () => {
  const local = snap({ p: { draft: file("laptop", 200), bib: file("bib-old", 100) } });
  const remote = snap({ p: { draft: file("phone", 150), bib: file("bib-new", 300) } });
  const { result, conflicts } = mergeSnapshots(local, remote, 0, NOW);
  assert.equal(result.projects.p.draft.content, "laptop");
  assert.equal(result.projects.p.bib.content, "bib-new");
  assert.equal(conflicts.length, 0);
});

test("projects from both sides are kept", () => {
  const { result } = mergeSnapshots(snap({ a: { draft: file("A", 1) } }), snap({ b: { draft: file("B", 2) } }), 0, NOW);
  assert.deepEqual(Object.keys(result.projects).sort(), ["a", "b"]);
});

test("a deletion wins over older versions but not newer edits", () => {
  const local = snap({ p: { draft: file("x", 100) } });
  const remote = snap({}, { p: NOW - 1000 });
  assert.ok(!("p" in mergeSnapshots(local, remote, 0, NOW).result.projects));
  const edited = snap({ p: { draft: file("edited after delete", NOW) } });
  assert.ok("p" in mergeSnapshots(edited, remote, 0, NOW).result.projects);
});

test("old tombstones are forgotten", () => {
  const { result } = mergeSnapshots(snap({}), snap({}, { p: NOW - 100 * 86400000 }), 0, NOW);
  assert.ok(!("p" in result.deleted));
});

test("edits made on both devices since the last sync are kept as a conflict copy", () => {
  const last = 1000;
  const local = snap({ p: { draft: file("laptop edit", 2000), bib: file("bib", 500) } });
  const remote = snap({ p: { draft: file("phone edit", 3000), bib: file("bib", 500) } });
  const { result, conflicts } = mergeSnapshots(local, remote, last, NOW);
  assert.equal(result.projects.p.draft.content, "phone edit");
  assert.equal(conflicts.length, 1);
  const copy = result.projects[conflicts[0].name];
  assert.match(conflicts[0].name, /^p - conflict \d{4}-\d{2}-\d{2} \d{4}$/);
  assert.equal(copy.draft.content, "laptop edit");
  assert.equal(copy.bib.content, "bib");
});

test("merging is idempotent", () => {
  const local = snap({ p: { draft: file("x", 5) } }, { q: NOW - 10 });
  const once = mergeSnapshots(local, snap({}), 0, NOW).result;
  const twice = mergeSnapshots(once, once, 0, NOW).result;
  assert.ok(sameSnapshot(once, twice));
});
