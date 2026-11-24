// settings.js — Settings panel: AI provider (server) and Google Drive sync (any device).
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
  const headers = () => ({
    "Content-Type": "application/json",
    "x-auth-token": (window.CONFIG && window.CONFIG.AUTH_TOKEN) || "",
  });
  const DOCS = "https://github.com/jobellet/research-assistant/blob/main/docs/sync-and-ai.md";

  const modal = document.createElement("div");
  modal.id = "settings-modal";
  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal-content settings-content" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div class="modal-header">
        <h2 id="settings-title">Settings</h2>
        <button class="close-modal" id="settings-close" aria-label="Close settings">×</button>
      </div>
      <div class="settings-body">
        <p id="settings-mode" class="settings-note"></p>

        <section class="settings-section server-only" id="ai-section">
          <h3>AI provider</h3>
          <p class="settings-note">Used by <b>Ask</b> and to identify papers that databases cannot match.
            Your key is stored on the server computer (<code>ai_settings.json</code>, never in git) and
            only sent to the provider you choose.</p>
          <label>Provider <select id="ai-provider"></select></label>
          <label id="ai-key-row">API key <input id="ai-key" type="password" autocomplete="off" /></label>
          <div id="ai-key-hint" class="settings-hint"></div>
          <label>Model <input id="ai-model" type="text" /></label>
          <label id="ai-base-row">Server URL <input id="ai-base" type="text" /></label>
          <div class="settings-actions">
            <button id="ai-save" class="view-btn active">Save</button>
            <button id="ai-test" class="view-btn">Test</button>
          </div>
          <div id="ai-status" class="settings-status" role="status" aria-live="polite"></div>
        </section>

        <section class="settings-section">
          <h3>Google Drive sync</h3>
          <p class="settings-note">Keeps your projects (<code>draft.tex</code>, <code>references.bib</code>)
            in sync between your computer and your phone through a private Google Drive app folder.
            <a href="${DOCS}" target="_blank" rel="noopener">How to set it up</a></p>
          <label>Google OAuth Client ID <input id="drive-client-id" type="text"
            placeholder="….apps.googleusercontent.com" autocomplete="off" /></label>
          <label class="settings-check"><input id="drive-auto" type="checkbox" />
            Sync automatically (after each save, and every 30 s while open)</label>
          <div class="settings-actions">
            <button id="drive-connect" class="view-btn active">Connect &amp; sync now</button>
            <button id="drive-disconnect" class="view-btn">Disconnect</button>
          </div>
          <div id="drive-status" class="settings-status" role="status" aria-live="polite"></div>
        </section>
      </div>
    </div>`;
  document.body.appendChild(modal);

  let providers = {};

  function open() {
    // close the phone side menu, which would cover the panel
    document.querySelector(".sidebar")?.classList.remove("show");
    document.getElementById("sidebar-overlay")?.classList.remove("show");
    modal.style.display = "flex";
    const browser = window.ProjectStore && window.ProjectStore.isBrowserMode();
    $("settings-mode").innerHTML = browser
      ? "📱 <b>Browser mode</b>: no research-assistant server here. Projects are stored in this browser; connect Google Drive to sync them with your computer."
      : "💻 Connected to your research-assistant server.";
    $("ai-section").style.display = browser ? "none" : "";
    if (!browser) loadAI();
    $("drive-client-id").value = window.GoogleAuth.getClientId();
    renderDrive(window.DriveSync.status());
  }
  function close() {
    modal.style.display = "none";
  }

  // ---------------------------------------------------------------- AI
  function showProviderFields() {
    const p = providers[$("ai-provider").value] || {};
    $("ai-key-row").style.display = $("ai-provider").value === "none" ? "none" : "";
    $("ai-base-row").style.display = $("ai-provider").value === "custom" ? "" : "none";
    $("ai-model").placeholder = p.default_model || "";
    $("ai-base").placeholder = p.base_url || "";
    $("ai-key-hint").innerHTML = p.key_hint ? `Get a key at <code>${esc(p.key_hint)}</code>` : "";
  }

  async function loadAI() {
    try {
      const r = await fetch("/api/ai/settings", { headers: headers() });
      const s = await r.json();
      providers = s.providers || {};
      $("ai-provider").innerHTML = Object.entries(providers)
        .map(([k, v]) => `<option value="${esc(k)}">${esc(v.label)}</option>`).join("");
      $("ai-provider").value = s.provider || "none";
      $("ai-model").value = s.source === "settings" || s.source === "env" ? (s.model || "") : "";
      $("ai-base").value = s.provider === "custom" ? (s.base_url || "") : "";
      $("ai-key").value = "";
      $("ai-key").placeholder = s.key_set ? `saved (${s.key_hint})` : "paste your API key";
      const from = { settings: "saved settings", env: ".env (AI_PROVIDER)", autodetect: "a key found in .env", none: "" }[s.source] || "";
      $("ai-status").textContent = s.enabled
        ? `Active: ${s.label} · ${s.model}${from ? " — from " + from : ""}`
        : "No AI provider: everything else works without one.";
      showProviderFields();
    } catch (e) {
      $("ai-status").textContent = "Could not load AI settings.";
    }
  }

  async function saveAI() {
    const key = $("ai-key").value.trim();
    const body = {
      provider: $("ai-provider").value,
      api_key: key ? key : null,
      model: $("ai-model").value.trim(),
      base_url: $("ai-base").value.trim(),
    };
    $("ai-status").textContent = "Saving…";
    const r = await fetch("/api/ai/settings", { method: "PUT", headers: headers(), body: JSON.stringify(body) });
    if (!r.ok) {
      $("ai-status").textContent = "Error: " + ((await r.json()).detail || r.status);
      return false;
    }
    await loadAI();
    // project-refs.js shows the "Check with AI" button only when a provider is set
    window.dispatchEvent(new CustomEvent("ai-settings-changed"));
    return true;
  }

  async function testAI() {
    if ($("ai-key").value.trim() && !(await saveAI())) return;
    $("ai-status").textContent = "Testing…";
    const r = await fetch("/api/ai/test", { method: "POST", headers: headers() });
    const d = await r.json();
    $("ai-status").textContent = r.ok ? `✓ ${d.label} · ${d.model} answered: "${d.answer}"` : "✗ " + (d.detail || r.status);
  }

  // ---------------------------------------------------------------- Drive
  function ago(ts) {
    if (!ts) return "never";
    const s = Math.round((Date.now() - ts) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    return new Date(ts).toLocaleString();
  }

  function renderDrive(st) {
    const el = $("drive-status");
    $("drive-auto").checked = st.autoSync;
    $("drive-disconnect").style.display = st.connected ? "" : "none";
    if (st.syncing) el.textContent = "Syncing…";
    else if (st.error) el.textContent = "✗ " + st.error;
    else if (!st.configured) el.textContent = "Add a Google OAuth Client ID to enable sync.";
    else if (!st.connected) el.textContent = `Not connected on this device (last sync: ${ago(st.lastSyncAt)}).`;
    else el.textContent = `✓ Connected · last sync ${ago(st.lastSyncAt)}`;
    const ind = $("sync-indicator");
    if (ind) {
      ind.textContent = st.syncing ? "⟳ Syncing…" : st.connected ? `☁ Synced ${ago(st.lastSyncAt)}` : "";
      ind.title = st.error || "";
      if (st.error && st.connected) ind.textContent = "☁ Sync error";
    }
  }

  async function connectDrive() {
    const id = $("drive-client-id").value.trim();
    if (!id.endsWith(".apps.googleusercontent.com")) {
      $("drive-status").textContent = "A Google OAuth Client ID ends with .apps.googleusercontent.com";
      return;
    }
    window.GoogleAuth.setClientId(id);
    try {
      const r = await window.DriveSync.syncNow({ interactive: true });
      if (r && r.conflicts && r.conflicts.length) {
        $("drive-status").textContent = `Synced. Edited on two devices: kept "${r.conflicts[0].name}".`;
      }
    } catch (e) {
      $("drive-status").textContent = "✗ " + e.message;
    }
  }

  $("btn-settings").addEventListener("click", open);
  $("settings-close").addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  window.addEventListener("keydown", (e) => { if (e.key === "Escape" && modal.style.display === "flex") close(); });
  $("ai-provider").addEventListener("change", () => {
    $("ai-model").value = "";
    $("ai-key").placeholder = "paste your API key";
    showProviderFields();
  });
  $("ai-save").addEventListener("click", saveAI);
  $("ai-test").addEventListener("click", testAI);
  $("drive-connect").addEventListener("click", connectDrive);
  $("drive-disconnect").addEventListener("click", () => window.DriveSync.disconnect());
  $("drive-auto").addEventListener("change", (e) => window.DriveSync.setAutoSync(e.target.checked));
  window.DriveSync.onChange(renderDrive);
  renderDrive(window.DriveSync.status());
  setInterval(() => renderDrive(window.DriveSync.status()), 30000);
  window.openSettings = open;
})();
