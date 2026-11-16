// google-auth.js — Google sign-in for Drive sync (adapted from ADHDtools services/google-auth.js).
// OAuth token flow with Google Identity Services: needs only an OAuth *Web* Client ID
// (no API key, no client secret). Tokens last ~1 hour and are cached in this browser.
(function () {
  "use strict";
  const CLIENT_ID_KEY = "ra-google-client-id";
  const TOKEN_PREFIX = "ra-google-token:";
  let gisPromise = null;
  let serverClientId = "";

  function getClientId() {
    try {
      return localStorage.getItem(CLIENT_ID_KEY) || serverClientId || "";
    } catch (e) {
      return serverClientId || "";
    }
  }
  function setClientId(id) {
    if (id) localStorage.setItem(CLIENT_ID_KEY, id.trim());
    else localStorage.removeItem(CLIENT_ID_KEY);
  }
  function setServerClientId(id) {
    serverClientId = id || "";
  }

  function loadGis() {
    if (window.google && window.google.accounts && window.google.accounts.oauth2) return Promise.resolve();
    if (gisPromise) return gisPromise;
    gisPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://accounts.google.com/gsi/client";
      s.async = true;
      s.onload = () => resolve();
      s.onerror = () => {
        gisPromise = null;
        reject(new Error("Could not load Google sign-in."));
      };
      document.head.appendChild(s);
    });
    return gisPromise;
  }

  function cachedToken(scope) {
    try {
      const raw = localStorage.getItem(TOKEN_PREFIX + scope);
      if (!raw) return null;
      const { token, expiresAt } = JSON.parse(raw);
      return token && Date.now() < expiresAt - 60000 ? token : null;
    } catch (e) {
      return null;
    }
  }
  function cacheToken(scope, token, expiresIn) {
    localStorage.setItem(TOKEN_PREFIX + scope, JSON.stringify({
      token, expiresAt: Date.now() + (parseInt(expiresIn, 10) || 3600) * 1000,
    }));
  }

  // interactive=false never opens a popup: it only returns a still-valid token.
  async function getAccessToken(scope, { interactive = true } = {}) {
    const cached = cachedToken(scope);
    if (cached) return cached;
    if (!interactive) return null;
    const clientId = getClientId();
    if (!clientId) throw new Error("Add your Google OAuth Client ID in Settings first.");
    await loadGis();
    return new Promise((resolve, reject) => {
      const client = window.google.accounts.oauth2.initTokenClient({
        client_id: clientId,
        scope,
        callback: (resp) => {
          if (resp.error) return reject(new Error(resp.error));
          cacheToken(scope, resp.access_token, resp.expires_in);
          resolve(resp.access_token);
        },
        error_callback: (err) => reject(new Error((err && err.type) || "Google sign-in was closed.")),
      });
      client.requestAccessToken({ prompt: "" });
    });
  }

  function hasSession(scope) {
    return Boolean(cachedToken(scope));
  }

  function signOut(scope) {
    const token = cachedToken(scope);
    localStorage.removeItem(TOKEN_PREFIX + scope);
    if (token && window.google && window.google.accounts) {
      try {
        window.google.accounts.oauth2.revoke(token, () => {});
      } catch (e) { /* best effort */ }
    }
  }

  window.GoogleAuth = { getClientId, setClientId, setServerClientId, getAccessToken, hasSession, signOut };
})();
