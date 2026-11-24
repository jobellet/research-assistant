// Service worker: opens the side panel, and grabs the selected text of the active tab
// (keyboard shortcut, right-click menu, or a request from the side panel).
import { docIdFromUrl } from "./lib.js";

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  chrome.contextMenus.create({
    id: "check-selection",
    title: "Check this claim in my references",
    contexts: ["selection"],
  });
});

/**
 * The selected text of a tab. Ordinary pages expose it through getSelection(). Google
 * Docs draws its text on a canvas, so there we ask the editor to copy its selection and
 * read the text from the copy event (the selection also ends up in the clipboard, as with
 * Ctrl+C).
 */
async function grabSelection(tabId) {
  let results = [];
  try {
    results = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: () => ((window.getSelection && window.getSelection().toString()) || "").trim(),
    });
  } catch (e) {
    const t = await chrome.tabs.get(tabId).catch(() => null);
    if (t && /^https?:/.test(t.url || "")) {
      return { error: "Chrome lets the extension read this page only right after you press Alt+Shift+K, or " +
        "right-click the selection and choose “Check this claim in my references”." };
    }
    return { error: "This page cannot be read by extensions (for example a chrome:// page)." };
  }
  const text = results.map((r) => r.result).find((t) => t && t.length > 2);
  if (text) return { text };
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (tab && docIdFromUrl(tab.url)) {
    try {
      const [r] = await chrome.scripting.executeScript({
        target: { tabId },
        func: () => {
          // Ask the Docs editor to copy its selection and catch the text it puts in the copy event.
          const frame = document.querySelector("iframe.docs-texteventtarget-iframe");
          const target = frame && frame.contentDocument;
          if (!target) return { copied: false };
          let text = "";
          const grab = (e) => {
            try { text = (e.clipboardData && e.clipboardData.getData("text/plain")) || text; } catch (err) { /* ignore */ }
          };
          target.addEventListener("copy", grab);
          document.addEventListener("copy", grab);
          let ok = false;
          try { ok = target.execCommand("copy"); } catch (e) { ok = false; }
          target.removeEventListener("copy", grab);
          document.removeEventListener("copy", grab);
          return { text: text.trim(), copied: ok };
        },
      });
      const out = (r && r.result) || {};
      // No text: nothing is selected, or Docs did not hand it over. The clipboard is NOT read
      // automatically (it may hold something unrelated, such as a password).
      return out.text ? { text: out.text, docs: true } : { docs: true };
    } catch (e) {
      return { docs: true };
    }
  }
  return {};
}

async function handOver(tab, grabbed) {
  await chrome.storage.session.set({ pending: { ...grabbed, tabId: tab.id, ts: Date.now() } });
}

chrome.commands.onCommand.addListener(async (command, tab) => {
  if (command !== "check-selection" || !tab) return;
  chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});   // needs the shortcut's user gesture
  await handOver(tab, await grabSelection(tab.id));
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "check-selection" || !tab) return;
  chrome.sidePanel.open({ tabId: tab.id }).catch(() => {});
  const text = (info.selectionText || "").trim();
  await handOver(tab, text ? { text } : await grabSelection(tab.id));
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "grab-selection" && Number.isInteger(msg.tabId)) {
    grabSelection(msg.tabId).then(sendResponse, (e) => sendResponse({ error: String((e && e.message) || e) }));
    return true;   // async answer
  }
  return false;
});
