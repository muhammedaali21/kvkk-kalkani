const $ = (id) => document.getElementById(id);

chrome.storage.local.get(["enabled", "useLlm"]).then(({ enabled, useLlm }) => {
  $("enabled").checked = enabled !== false;
  $("useLlm").checked = useLlm !== false;
});
$("enabled").onchange = (e) => chrome.storage.local.set({ enabled: e.target.checked });
$("useLlm").onchange = (e) => chrome.storage.local.set({ useLlm: e.target.checked });

chrome.runtime.sendMessage({ type: "health" }, (r) => {
  if (r && r.ok) {
    $("server").textContent = "çalışıyor";
    $("server").className = "ok";
    $("model").textContent = r.llm ? r.model : "Gemma kapalı";
    $("model").className = r.llm ? "ok" : "bad";
  } else {
    $("server").textContent = "kapalı";
    $("server").className = "bad";
    $("model").textContent = "—";
  }
});
