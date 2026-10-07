import { translate } from "./api.js";

const MENU_ID = "lt-translate-selection";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: "Translate with Echoglass",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === MENU_ID && tab?.id) translateInPlace(tab.id, info.frameId ?? 0);
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "translate-selection") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) translateInPlace(tab.id, 0);
});

// Exposed for automated tests (service-worker scope only, not reachable from web pages).
self.__ltTranslateInPlace = (tabId, frameId = 0) => translateInPlace(tabId, frameId);

async function run(tabId, frameId, func, args = []) {
  const [res] = await chrome.scripting.executeScript({
    target: { tabId, frameIds: [frameId] },
    func,
    args,
  });
  return res?.result;
}

async function translateInPlace(tabId, frameId) {
  let text;
  try {
    text = await run(tabId, frameId, captureSelection);
  } catch (e) {
    // e.g. chrome:// pages or the Web Store, where extensions can't run
    console.warn("Echoglass: can't access this page", e);
    return;
  }
  if (!text) return;
  try {
    const { translation } = await translate(text);
    await run(tabId, frameId, applyTranslation, [translation]);
  } catch (e) {
    await run(tabId, frameId, showError, [String(e.message || e)]);
  }
}

// ---- functions injected into the page --------------------------------------------------
// These run in the page, not here, so they can't use anything outside their own body.

function captureSelection() {
  const el = document.activeElement;
  const toast = (msg) => {
    let t = document.getElementById("__lt_toast");
    if (!t) {
      t = document.createElement("div");
      t.id = "__lt_toast";
      Object.assign(t.style, {
        position: "fixed", right: "20px", bottom: "20px", zIndex: 2147483647,
        background: "#15181e", color: "#e7e9ee", border: "1px solid #2a2f52",
        borderRadius: "10px", padding: "9px 14px", font: "13px system-ui, sans-serif",
        boxShadow: "0 6px 24px rgba(0,0,0,.35)", maxWidth: "360px",
      });
      document.documentElement.appendChild(t);
    }
    t.textContent = msg;
  };

  // Text fields: remember the selected character range.
  if (el && (el.tagName === "TEXTAREA" ||
      (el.tagName === "INPUT" && /^(text|search|url|email|)$/i.test(el.type)))) {
    const start = el.selectionStart, end = el.selectionEnd;
    if (start == null || start === end) return "";
    window.__ltTarget = { kind: "input", el, start, end };
    toast("Translating…");
    return el.value.slice(start, end);
  }

  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return "";
  window.__ltTarget = { kind: "range", range: sel.getRangeAt(0).cloneRange() };
  toast("Translating…");
  return sel.toString();
}

function applyTranslation(translation) {
  document.getElementById("__lt_toast")?.remove();
  const target = window.__ltTarget;
  window.__ltTarget = null;
  if (!target || !translation) return;

  if (target.kind === "input") {
    const { el, start, end } = target;
    el.focus();
    el.setRangeText(translation, start, end, "select");
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }

  const { range } = target;
  const original = range.extractContents(); // kept so Alt+click can restore it
  const originalText = original.textContent;
  const span = document.createElement("span");
  span.className = "__lt_translated";
  span.title = `Original: ${originalText}\n(Alt+click to restore)`;
  Object.assign(span.style, {
    backgroundColor: "rgba(139,156,255,0.16)",
    borderBottom: "1px dotted rgba(139,156,255,0.9)",
    borderRadius: "2px",
  });
  translation.split("\n").forEach((line, i) => {
    if (i) span.appendChild(document.createElement("br"));
    span.appendChild(document.createTextNode(line));
  });
  span.addEventListener("click", (ev) => {
    if (!ev.altKey) return;
    ev.preventDefault();
    span.replaceWith(original);
  });
  range.insertNode(span);
  window.getSelection()?.removeAllRanges();
}

function showError(message) {
  window.__ltTarget = null;
  let t = document.getElementById("__lt_toast");
  if (!t) return alert(`Echoglass: ${message}`);
  t.textContent = message;
  t.style.borderColor = "#ff6b6b";
  setTimeout(() => t.remove(), 5000);
}
