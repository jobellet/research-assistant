import { DEFAULT_SERVER, VERDICT, api, docIdFromUrl, docMobilePathFromUrl, esc, htmlToText, looksLikeDocHtml,
  normalizeServer, renderAudit, renderEvidence } from "./lib.js";

const $ = (id) => document.getElementById(id);
const st = { server: DEFAULT_SERVER, token: "", project: "", groups: [], groupsProject: "", seq: 0,
  aiEnabled: false, docCache: { key: null, text: null, at: 0 }, auditTimer: null };

function status(msg, bad = false) {
  $("status").textContent = msg || "";
  $("status").classList.toggle("bad", !!bad);
}
const call = (path, opts) => api(st.server, st.token, path, opts);
const P = () => encodeURIComponent(st.project);

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab || null;
}

// ------------------------------------------------------------------ settings and projects
async function loadSettings() {
  const s = await chrome.storage.local.get(["server", "token", "docProjects", "lastProject"]);
  st.server = s.server || DEFAULT_SERVER;
  st.token = s.token || "";
  st.docProjects = s.docProjects || {};
  st.lastProject = s.lastProject || "";
  $("server").value = st.server;
  $("password").value = st.token;
}

async function saveSettings() {
  try {
    st.server = normalizeServer($("server").value);
  } catch (e) { status(e.message, true); return; }
  st.token = $("password").value;
  await chrome.storage.local.set({ server: st.server, token: st.token });
  $("settings").hidden = true;
  $("btn-settings").setAttribute("aria-expanded", "false");
  await loadProjects();
}

async function loadProjects() {
  if (!st.token) {
    $("settings").hidden = false;
    status("Enter the password of your research-assistant server (SERVER_PASSWORD).");
    return;
  }
  try {
    const { projects } = await call("/api/projects");
    const tab = await activeTab();
    const docId = tab && docIdFromUrl(tab.url);
    const wanted = (docId && st.docProjects[docId]) || st.lastProject;
    if (!projects.length) {
      $("project").innerHTML = '<option value="" disabled selected>No project</option>';
      st.project = "";
      status("No project yet: create one in the research-assistant app, then reopen this panel.", true);
      return;
    }
    $("project").innerHTML = projects.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
    st.project = projects.includes(wanted) ? wanted : projects[0] || "";
    $("project").value = st.project;
    status(`Connected to ${st.server}.`);
    try { st.aiEnabled = !!(await call("/api/ai/settings")).enabled; } catch (e) { st.aiEnabled = false; }
    await showProjectInfo();
  } catch (e) {
    status(e.message, true);
    if (/password/i.test(e.message)) $("settings").hidden = false;
  }
}

async function showProjectInfo() {
  if (!st.project) return;
  try {
    const r = await call(`/api/projects/${P()}/refs`);
    const n = (r.papers || []).length;
    const z = r.zotero ? ` · Zotero: ${r.zotero.collection_name}` : "";
    status(n ? `${n} paper(s) in “${st.project}”${z}.` : `“${st.project}” has no papers yet: link a Zotero collection in the app.`, !n);
  } catch (e) { status(e.message, true); }
}

async function chooseProject() {
  if ($("project").value !== st.project) {
    st.seq++;                                   // results of the previous project are dropped
    clearInterval(st.auditTimer);
  }
  st.project = $("project").value;
  const tab = await activeTab();
  const docId = tab && docIdFromUrl(tab.url);
  if (docId) st.docProjects[docId] = st.project;     // remember the project of each Doc
  await chrome.storage.local.set({ docProjects: st.docProjects, lastProject: st.project });
  await showProjectInfo();
}

// ------------------------------------------------------------------ Google Doc text
/** Plain text of the Google Doc open in ``tab`` (Docs' own text export, with your session). */
async function docText(tab, maxAgeMs = 60000) {
  const path = docMobilePathFromUrl(tab && tab.url);
  if (!path) return null;
  if (st.docCache.key === path && Date.now() - st.docCache.at < maxAgeMs) return st.docCache.text;
  // The page fetches its own 'mobilebasic' HTML (same origin, your session); the text is
  // extracted here. (The .txt export redirects to another domain the page cannot read.)
  const [r] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: async (path) => {
      const res = await fetch(path, { credentials: "include" });
      if (!res.ok) return { error: res.status };
      return { html: await res.text() };
    },
    args: [path],
  });
  const out = r && r.result;
  if (!out || out.error) throw new Error(`Could not read the document (Google Docs answered ${out ? out.error : "nothing"}).`);
  if (!looksLikeDocHtml(out.html)) throw new Error("Google Docs did not return the document (is this account allowed to open it?).");
  const text = htmlToText(out.html);
  st.docCache = { key: path, text, at: Date.now() };
  return text;
}

// ------------------------------------------------------------------ clipboard
async function readClipboard() {
  try {
    const t = await navigator.clipboard.readText();
    if (t) return t;
  } catch (e) { /* not focused: try the old way */ }
  const ta = document.createElement("textarea");
  ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.focus();
  let ok = false;
  try { ok = document.execCommand("paste"); } catch (e) { ok = false; }
  const t = ta.value;
  ta.remove();
  return ok ? t : "";
}

// ------------------------------------------------------------------ checking a claim
function noProjectMessage() {
  return $("project").options.length && $("project").value ? "Choose a project."
    : "No project yet: create one in the research-assistant app, then reopen this panel.";
}

async function checkClaim(text, tabId = null) {
  text = (text || "").replace(/\s+/g, " ").trim();
  if (!text) { status("Nothing selected.", true); return; }
  if (!st.project) { status(noProjectMessage(), true); return; }
  if (text.length > 5000) { status("Select a shorter passage (at most 5000 characters).", true); return; }
  const seq = ++st.seq;
  clearInterval(st.auditTimer);
  $("results-head").hidden = false;
  $("results-title").textContent = "Matching sentences";
  $("btn-judge").hidden = true;
  $("results").innerHTML = `<p class="note">Checking “${esc(text.slice(0, 200))}”…</p>`;
  const body = { text, per_paper: 3, top_k: 10 };
  const project = st.project;
  const tab = tabId != null ? await chrome.tabs.get(tabId).catch(() => null) : await activeTab();
  try {
    const doc = await docText(tab);
    if (doc) body.document_text = doc;          // its numbered reference list identifies the cited papers
  } catch (e) { /* the claim is still checked; numbered citations stay unresolved */ }
  try {
    const data = await call(`/api/projects/${encodeURIComponent(project)}/evidence`, { method: "POST", body });
    if (seq !== st.seq) return;
    st.groups = [];
    st.groupsProject = project;
    $("results").innerHTML = `<p class="note">${esc(data.claim)}</p>` + renderEvidence(data, st.groups);
    $("btn-judge").hidden = !st.aiEnabled;
    $("btn-judge").disabled = false;
    $("btn-judge").textContent = "Check with AI";
    status(data.numbered_references ? `Citations read from the document's ${data.numbered_references} numbered references.`
      : "");
  } catch (e) {
    if (seq === st.seq) $("results").innerHTML = `<p class="note bad">${esc(e.message)}</p>`;
  }
}

async function checkSelection() {
  const tab = await activeTab();
  if (!tab) return;
  status("Reading the selection…");
  try {
    const r = await chrome.runtime.sendMessage({ type: "grab-selection", tabId: tab.id });
    await usePending({ ...(r || {}), tabId: tab.id });
  } catch (e) {
    status(String((e && e.message) || e), true);
  }
}

async function usePending(r) {
  if (!r) return;
  if (r.error) { status(r.error, true); return; }
  if (r.text) { await checkClaim(r.text, r.tabId); return; }
  status(r.docs ? "Nothing selected, or Google Docs did not hand over the selection: select the sentence, press ⌘C / Ctrl+C, then click “Check copied text”."
    : "Nothing selected in the page.", true);
}

async function checkClipboard() {
  const t = await readClipboard();
  if (!t) { status("The clipboard is empty, or Chrome refused to read it.", true); return; }
  await checkClaim(t);
}

async function judge() {
  const btn = $("btn-judge");
  btn.disabled = true;
  btn.textContent = "Checking…";
  const seq = st.seq;
  try {
    await Promise.all(st.groups.map(async (g, gi) => {
      if (!g.passages.length) return;
      const r = await call(`/api/projects/${encodeURIComponent(st.groupsProject)}/evidence/judge`, {
        method: "POST", body: { claim: g.claim, passages: g.passages.slice(0, 12) } });
      if (seq !== st.seq) return;
      (r.verdicts || []).forEach((v) => {
        const el = document.querySelector(`.passage[data-group="${gi}"][data-pass="${v.i}"] .verdict`);
        if (!el) return;
        const [label, cls] = VERDICT[v.verdict] || [v.verdict, "muted"];
        el.hidden = false;
        el.innerHTML = `<strong class="${cls}">${esc(label)}</strong> ${esc(v.reason)}`;
      });
    }));
    btn.textContent = "Checked ✓";
  } catch (e) {
    status(e.message, true);
    btn.textContent = "Check with AI";
    btn.disabled = false;
  }
}

// ------------------------------------------------------------------ audit of the whole Doc
async function auditDoc() {
  const tab = await activeTab();
  if (!docIdFromUrl(tab && tab.url)) { status("Open the Google Doc to audit in this tab.", true); return; }
  if (!st.project) { status(noProjectMessage(), true); return; }
  const seq = ++st.seq;
  clearInterval(st.auditTimer);
  const proj = encodeURIComponent(st.project);
  let timer = null;
  $("btn-judge").hidden = true;
  $("results-head").hidden = false;
  $("results-title").textContent = "Citation audit";
  $("results").innerHTML = `<p class="note">Reading the document…</p>`;
  try {
    const text = await docText(tab, 0);
    const title = (tab.title || "").replace(/ - Google (Docs|Documents)$/i, "");
    await call(`/api/projects/${proj}/citation-audit`, { method: "POST", body: { text, source: title } });
    const poll = async () => {
      if (seq !== st.seq) { clearInterval(timer); return; }
      const r = await call(`/api/projects/${proj}/citation-audit`);
      if (seq !== st.seq) { clearInterval(timer); return; }
      const job = r.job || {};
      if (job.running) {
        $("results").innerHTML = `<p class="note">Auditing… ${esc(job.done || 0)}/${esc(job.total || "?")} ` +
          `(DOIs are checked in Crossref; this takes a few minutes).</p>`;
        return;
      }
      clearInterval(timer);
      if (job.error) throw new Error(job.error);
      $("results").innerHTML = r.report ? renderAudit(r.report) : `<p class="note bad">No report.</p>`;
    };
    timer = st.auditTimer = setInterval(() => poll().catch((e) => {
      clearInterval(timer);
      if (seq === st.seq) $("results").innerHTML = `<p class="note bad">${esc(e.message)}</p>`;
    }), 4000);
    await poll();
  } catch (e) {
    clearInterval(timer);
    if (seq === st.seq) $("results").innerHTML = `<p class="note bad">${esc(e.message)}</p>`;
  }
}

// ------------------------------------------------------------------ result buttons
$("results").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.pdf) {
    // Fetched with the password in a header, then opened from memory: the password never
    // appears in a URL (history, sync, server log).
    try {
      const res = await fetch(`${st.server}/api/pdf/${encodeURIComponent(b.dataset.pdf)}`,
        { headers: { "x-auth-token": st.token } });
      if (!res.ok) throw new Error(`The server could not send the PDF (${res.status}).`);
      const url = URL.createObjectURL(await res.blob());
      chrome.tabs.create({ url: `${url}#page=${encodeURIComponent(b.dataset.page)}` });
      setTimeout(() => URL.revokeObjectURL(url), 10 * 60 * 1000);
    } catch (err) { status(err.message, true); }
  } else if (b.dataset.copy) {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied!"; } catch (err) { status("Copy failed.", true); }
    setTimeout(() => { b.textContent = "Copy"; }, 1200);
  }
});

// ------------------------------------------------------------------ wiring
async function refreshDocHint() {
  const tab = await activeTab();
  $("docs-hint").hidden = !docIdFromUrl(tab && tab.url);
  $("btn-audit").disabled = !docIdFromUrl(tab && tab.url);
}

$("btn-settings").addEventListener("click", () => {
  const open = $("settings").hidden;
  $("settings").hidden = !open;
  $("btn-settings").setAttribute("aria-expanded", String(open));
});
$("btn-save").addEventListener("click", saveSettings);
$("project").addEventListener("change", chooseProject);
$("btn-selection").addEventListener("click", checkSelection);
$("btn-clipboard").addEventListener("click", checkClipboard);
$("btn-check").addEventListener("click", () => checkClaim($("claim").value));
$("btn-audit").addEventListener("click", auditDoc);
$("btn-judge").addEventListener("click", judge);
chrome.tabs.onActivated.addListener(() => { refreshDocHint(); loadProjects(); });
chrome.tabs.onUpdated.addListener((id, info) => { if (info.url) { refreshDocHint(); } });

// The keyboard shortcut and the right-click menu hand the selection over through session storage.
const ready = (async () => {
  await loadSettings();
  await refreshDocHint();
  await loadProjects();
})();

/** Handle a selection handed over by the shortcut or the menu, if it belongs to this window. */
async function takePending(p) {
  if (!p || Date.now() - p.ts > 15000) return;
  const [tab, win] = await Promise.all([chrome.tabs.get(p.tabId).catch(() => null), chrome.windows.getCurrent()]);
  if (!tab || tab.windowId !== win.id) return;   // the panel of the other window takes it
  await chrome.storage.session.remove("pending");
  await ready;
  usePending(p);
}

chrome.storage.session.onChanged.addListener((changes) => {
  if (changes.pending && changes.pending.newValue) takePending(changes.pending.newValue);
});

ready.then(async () => {
  const { pending } = await chrome.storage.session.get("pending");
  takePending(pending);
});
