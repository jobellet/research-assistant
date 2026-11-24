// Regression tests for the paper cards (app.js) and the project references UI
// (project-refs.js). Both are browser scripts, so they run in a vm context with
// small stubs for the DOM pieces they touch. All data here is invented.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const APP = readFileSync(new URL("../../frontend_module/app.js", import.meta.url), "utf8");
const REFS = readFileSync(new URL("../../frontend_module/project-refs.js", import.meta.url), "utf8");
const CSS = readFileSync(new URL("../../frontend_module/style.css", import.meta.url), "utf8");

// Source text of a top-level `function name(...) {...}` in app.js (brace matching).
function extractFunction(src, name) {
  const start = src.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `function ${name} not found`);
  let i = src.indexOf("{", src.indexOf(")", start));
  let depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(start, i + 1);
  }
  throw new Error("unbalanced braces");
}

function cardHelpers() {
  const calls = [];
  const ctx = vm.createContext({
    window: {
      openPDF: (...a) => calls.push(["pdf", ...a]),
      openQuickGraph: (...a) => calls.push(["graph", ...a]),
      openRawText: (...a) => calls.push(["text", ...a]),
      discoverRelated: (...a) => calls.push(["related", ...a]),
      addToBib: (...a) => calls.push(["cite", ...a]),
    },
  });
  const code = ["escHtml", "fileButtonsHtml", "paperActionsHtml", "onPaperAction"]
    .map((n) => extractFunction(APP, n)).join("\n") +
    "\n({ escHtml, fileButtonsHtml, paperActionsHtml, onPaperAction });";
  return { ...vm.runInContext(code, ctx), calls };
}

// Minimal HTML attribute reader for the generated buttons
function attrs(tag) {
  const out = {};
  for (const m of tag.matchAll(/([\w-]+)="([^"]*)"/g)) out[m[1]] = m[2];
  return out;
}
const unesc = (s) => s.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<")
  .replace(/&gt;/g, ">").replace(/&amp;/g, "&");

test("paper buttons survive apostrophes and quotes in file names and titles", () => {
  const { paperActionsHtml, onPaperAction, calls } = cardHelpers();
  const file = "O'Neill and Smith - 2001 - A \"quoted\" title.pdf";
  const title = 'Area X shows "feature alpha" <i>in vivo</i>';
  const html = paperActionsHtml("abc123", title, [{ filename: file }], "bib-btn-");
  assert.doesNotMatch(html, /onclick/);
  assert.doesNotMatch(html, /<i>/);
  const buttons = [...html.matchAll(/<button[^>]*>/g)].map((m) => attrs(m[0]));
  const pdf = buttons.find((b) => b["data-paper-action"] === "pdf");
  const text = buttons.find((b) => b["data-paper-action"] === "text");
  assert.equal(unesc(pdf["data-file"]), file);
  assert.equal(unesc(text["data-title"]), title);
  assert.ok(buttons.some((b) => b.id === "bib-btn-abc123"));

  // The delegated handler passes the exact values on.
  const fakeBtn = (b) => ({
    dataset: { paperAction: b["data-paper-action"], hash: b["data-hash"],
      file: b["data-file"] && unesc(b["data-file"]), title: b["data-title"] && unesc(b["data-title"]) },
  });
  for (const b of buttons) onPaperAction({ target: { closest: () => fakeBtn(b) } });
  assert.deepEqual(calls.find((c) => c[0] === "pdf"), ["pdf", "abc123", file]);
  assert.deepEqual(calls.find((c) => c[0] === "text"), ["text", "abc123", title]);
  assert.ok(calls.some((c) => c[0] === "cite" && c[1] === "abc123"));
});

test("card text fields are escaped", () => {
  const { escHtml } = cardHelpers();
  assert.equal(escHtml(`<img src=x onerror="alert(1)"> van Dijk's`),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; van Dijk&#39;s");
  assert.equal(escHtml(null), "");
  // renderLibrary / renderResults must not interpolate raw metadata any more
  for (const fn of ["renderLibrary", "renderResults"]) {
    const body = extractFunction(APP, fn);
    assert.doesNotMatch(body, /onclick=/, fn);
    assert.doesNotMatch(body, /\$\{(title|summary|authors|keywords)\}/, fn);
  }
});

test("loadLibrary ignores responses of older requests", () => {
  const body = extractFunction(APP, "loadLibrary");
  assert.match(body, /seq !== state\.librarySeq/);
});

test("the hidden attribute wins over author display rules", () => {
  assert.match(CSS, /\[hidden\]\s*\{\s*display:\s*none\s*!important;\s*\}/);
});

// ---------------------------------------------------------------- project-refs.js

function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

function el(id) {
  const listeners = {};
  return {
    id, hidden: false, innerHTML: "", textContent: "", value: "", checked: false, disabled: false, dataset: {},
    files: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    fire: (t, e) => (listeners[t] || []).forEach((f) => f(e)),
    setAttribute() {}, focus() {}, click() {},
    querySelector: () => null,
  };
}

// Load project-refs.js with stubs. `routes` maps "METHOD path" to a function
// returning the response body (or a promise of it).
function loadRefs({ routes, confirm = () => true, appState = {} }) {
  const els = {};
  const $ = (id) => (els[id] = els[id] || el(id));
  const requests = [];
  const toasts = [];
  const confirms = [];
  const winListeners = {};
  const docListeners = {};
  const ctx = {
    CONFIG: { API_BASE: "", AUTH_TOKEN: "t" },
    authHeaders: () => ({}),
    showToast: (m) => toasts.push(m),
    localStorage: { getItem: () => null, setItem() {} },
    state: { serverMode: undefined, activeProject: null, activeFile: "draft", view: "editor", ...appState },
    editor: { value: "", dispatchEvent() {} },
    saveStatus: { textContent: "Saved" },
    Event: class { constructor(t) { this.type = t; } },
    CustomEvent: class { constructor(t) { this.type = t; } },
    setTimeout, clearTimeout, setInterval: () => 0, console, Promise, String, Number, Math, Date, JSON, Error,
    encodeURIComponent,
    fetch: async (url, opts = {}) => {
      const key = `${opts.method || "GET"} ${url}`;
      requests.push(key);
      const route = Object.keys(routes).find((k) => key.startsWith(k));
      if (!route) return { ok: false, status: 404, json: async () => ({ detail: "no route " + key }) };
      const body = await routes[route](opts);
      return { ok: true, status: 200, json: async () => body };
    },
    document: {
      readyState: "loading",
      getElementById: $,
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener: (t, f) => { docListeners[t] = f; },
      visibilityState: "visible",
    },
  };
  ctx.window = {
    confirm: (m) => { confirms.push(m); return confirm(m); },
    addEventListener: (t, f) => { (winListeners[t] = winListeners[t] || []).push(f); },
    dispatchEvent: (e) => (winListeners[e.type] || []).forEach((f) => f(e)),
    ProjectStore: {},
  };
  vm.createContext(ctx);
  vm.runInContext(REFS, ctx);
  return { ctx, els, $, requests, toasts, confirms, docListeners, refs: ctx.window.ProjectRefsUI };
}

const PAPERS = { papers: [{ hash_id: "p1", indexed: true }], zotero: null, job: {} };
const EVIDENCE = (title) => ({
  claim: "Area X shows feature alpha",
  papers: [{ hash_id: "p1", title, passages: [{ text: "Area X shows feature alpha in all samples.", similarity: 0.9 }] }],
});

test("'Check with AI' appears although serverMode was unknown at script start (finding 9)", async () => {
  const t = loadRefs({ routes: {
    "GET /api/projects/A/refs": () => PAPERS,
    "GET /api/ai/settings": () => ({ enabled: true }),
    "POST /api/projects/A/evidence": () => EVIDENCE("Smith 2020"),
  } });
  t.docListeners.DOMContentLoaded();          // start(): serverMode still undefined here
  t.ctx.state.serverMode = true;               // app.js init sets it later
  t.refs.onProjectChanged("A");
  await tick(); await tick();
  await t.refs.findEvidence("Area X shows feature alpha");
  assert.match(t.$("evidence-section").innerHTML, /btn-evidence-judge/);
});

test("evidence of the previous project is not shown after a project switch (finding 12)", async () => {
  const pending = deferred();
  const t = loadRefs({ appState: { serverMode: true }, routes: {
    "GET /api/projects/A/refs": () => PAPERS,
    "GET /api/projects/B/refs": () => PAPERS,
    "GET /api/ai/settings": () => ({ enabled: false }),
    "POST /api/projects/A/evidence": () => pending.promise,
  } });
  t.refs.onProjectChanged("A");
  await tick(); await tick();
  const search = t.refs.findEvidence("Area X shows feature alpha");
  await tick();
  t.refs.onProjectChanged("B");
  pending.resolve(EVIDENCE("Paper of project A"));
  await search;
  assert.doesNotMatch(t.$("evidence-section").innerHTML, /Paper of project A/);
});

test("importing a .docx from the bib tab asks before replacing a written draft (finding 11)", async () => {
  const loaded = [];
  const t = loadRefs({
    appState: { serverMode: true, activeProject: "A", activeFile: "bib", loadedFile: "A/bib" },
    confirm: () => false,
    routes: { "GET /api/projects/A/refs": () => PAPERS, "GET /api/ai/settings": () => ({ enabled: false }) },
  });
  t.ctx.window.ProjectStore.read = async (p, f) => {
    loaded.push(`${p}/${f}`);
    return { content: f === "draft" ? "\\section{Intro} My own draft text." : "" };
  };
  t.ctx.editor.value = "";                     // empty references.bib open
  t.refs.onProjectChanged("A");
  t.docListeners.DOMContentLoaded();
  const input = t.$("docx-file-input");
  input.files = [{ name: "draft.docx" }];
  input.fire("change");
  await tick(); await tick();
  assert.equal(t.confirms.length, 1, "confirm() must be shown for the stored draft");
  assert.ok(loaded.includes("A/draft"));
  assert.ok(!t.requests.some((r) => r.includes("import-docx")), "declined: nothing imported");
});

test("changing the library scope re-runs the paper matches of the selection (finding 15)", async () => {
  const t = loadRefs({ appState: { serverMode: true, lastSelection: "Area X shows feature alpha",
    lastSearchedText: "Area X shows feature alpha" }, routes: {} });
  const searched = [];
  t.ctx.performSemanticSearch = (q) => searched.push(q);
  t.ctx.loadLibrary = () => {};
  t.docListeners.DOMContentLoaded();
  t.$("scope-all").fire("click");
  assert.deepEqual(searched, ["Area X shows feature alpha"]);
});
