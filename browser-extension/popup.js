import { call, getPrefs, translate } from "./api.js";

const LANGUAGES = {
  en: "English", ko: "Korean", ja: "Japanese", zh: "Chinese", es: "Spanish", fr: "French",
  de: "German", it: "Italian", pt: "Portuguese", ru: "Russian", tr: "Turkish", nl: "Dutch",
  pl: "Polish", uk: "Ukrainian", id: "Indonesian", vi: "Vietnamese", th: "Thai", ar: "Arabic",
  hi: "Hindi",
};

const $ = (id) => document.getElementById(id);
let status = null;

async function refresh() {
  try {
    status = await call("/api/status");
    $("conn").textContent = status.running ? "Live" : "Connected";
    $("conn").className = "conn ok";
    $("controls").hidden = false;
    $("live").textContent = status.running ? "Stop live translation" : "Start live translation";
    $("live").classList.toggle("running", status.running);
    $("live").disabled = status.busy;
    $("overlay").classList.toggle("on", status.overlay);
    const appTarget = $("target").querySelector('option[value=""]');
    appTarget.textContent = `Same as app (${LANGUAGES[status.target] || status.target})`;
  } catch {
    status = null;
    $("conn").textContent = "App not running";
    $("conn").className = "conn bad";
    $("controls").hidden = true;
  }
}

async function init() {
  const prefs = await getPrefs();
  const sel = $("target");
  sel.append(new Option("Same as app", ""));
  for (const [code, name] of Object.entries(LANGUAGES)) sel.append(new Option(name, code));
  sel.value = prefs.target;
  $("port").value = prefs.port;

  sel.addEventListener("change", () => chrome.storage.sync.set({ target: sel.value }));
  $("port").addEventListener("change", async () => {
    const port = Number($("port").value);
    if (port >= 1024 && port <= 65535) {
      await chrome.storage.sync.set({ port });
      refresh();
    }
  });

  $("live").addEventListener("click", async () => {
    $("live").disabled = true;
    await call("/api/live", { action: "toggle" }).catch(() => {});
    setTimeout(refresh, 400);
  });
  $("overlay").addEventListener("click", async () => {
    await call("/api/overlay", {}).catch(() => {});
    setTimeout(refresh, 200);
  });

  $("go").addEventListener("click", doTranslate);
  $("text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) doTranslate();
  });
  $("copy").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("result").textContent);
    $("copy").textContent = "Copied";
    setTimeout(() => ($("copy").textContent = "Copy"), 1200);
  });

  await refresh();
  setInterval(refresh, 2000);
  $("text").focus();
}

async function doTranslate() {
  const text = $("text").value.trim();
  if (!text) return;
  $("go").disabled = true;
  $("go").textContent = "…";
  $("out").hidden = false;
  $("out").classList.remove("error");
  try {
    const { translation } = await translate(text);
    $("result").textContent = translation;
    $("copy").hidden = false;
  } catch (e) {
    $("out").classList.add("error");
    $("result").textContent = e.message;
    $("copy").hidden = true;
  } finally {
    $("go").disabled = false;
    $("go").textContent = "Translate";
  }
}

init();
