// Tüm sunucu istekleri buradan atılır; böylece sohbet sitelerinin CORS/CSP kurallarına takılmayız.
const API = "http://127.0.0.1:8765";

async function getSession() {
  // Tek kalıcı oturum: aynı kişi her sohbette aynı etiketi alır, eski sohbetler de geri çevrilebilir.
  const { session } = await chrome.storage.local.get("session");
  if (session) return session;
  const fresh = "ext-" + crypto.randomUUID().slice(0, 8);
  await chrome.storage.local.set({ session: fresh });
  return fresh;
}

async function call(path, options = {}) {
  const r = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!r.ok) throw new Error(`Sunucu hatası: ${r.status}`);
  return r.json();
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      const session = await getSession();
      if (msg.type === "mask") {
        const { useLlm = true } = await chrome.storage.local.get("useLlm");
        const r = await call("/mask", {
          method: "POST",
          body: JSON.stringify({ text: msg.text, session, use_llm: useLlm }),
        });
        sendResponse({ ok: true, ...r });
      } else if (msg.type === "maskImage") {
        // Ekran görüntüsü: yerel sunucuda OCR + Gemma 4 ile karartılır, karartılmış PNG geri döner.
        const { useLlm = true } = await chrome.storage.local.get("useLlm");
        const blob = await (await fetch(msg.dataUrl)).blob();
        const fd = new FormData();
        fd.append("file", blob, msg.name || "ekran.png");
        fd.append("session", session);
        fd.append("use_llm", useLlm ? "true" : "false");
        const r = await fetch(API + "/mask-file", { method: "POST", body: fd });
        if (!r.ok) throw new Error(`Sunucu hatası: ${r.status}`);
        const report = JSON.parse(r.headers.get("X-Kalkan-Report") || "{}");
        const bytes = new Uint8Array(await r.arrayBuffer());
        let bin = "";
        for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        sendResponse({ ok: true, dataUrl: "data:image/png;base64," + btoa(bin), report });
      } else if (msg.type === "mapping") {
        sendResponse({ ok: true, mapping: await call(`/mapping/${session}`) });
      } else if (msg.type === "health") {
        sendResponse({ ok: true, ...(await call("/health")) });
      } else {
        sendResponse({ ok: false, error: "bilinmeyen istek" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String(e.message || e) });
    }
  })();
  return true; // asenkron cevap
});
