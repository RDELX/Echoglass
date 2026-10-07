// Talks to the Echoglass desktop app's local API (127.0.0.1 only).
export const DEFAULTS = { port: 47821, target: "" }; // target "" = use the app's target language

export async function getPrefs() {
  return { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
}

// Always POST: Chrome only sends the Origin header (which the app checks) on POSTs.
export async function call(path, body = {}) {
  const { port } = await getPrefs();
  let res;
  try {
    res = await fetch(`http://127.0.0.1:${port}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("The Echoglass app isn't running. Start it and try again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Echoglass returned ${res.status}`);
  return data;
}

export async function translate(text) {
  const { target } = await getPrefs();
  return call("/api/translate", { text, target: target || undefined });
}
