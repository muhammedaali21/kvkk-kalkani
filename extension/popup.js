const $ = (id) => document.getElementById(id);

chrome.storage.local.get(["enabled", "useLlm"]).then(({ enabled, useLlm }) => {
  $("enabled").checked = enabled !== false;
  $("useLlm").checked = useLlm !== false;
});
$("enabled").onchange = (e) => chrome.storage.local.set({ enabled: e.target.checked });
$("useLlm").onchange = (e) => chrome.storage.local.set({ useLlm: e.target.checked });

chrome.runtime.sendMessage({ type: "health" }, (r) => {
  if (r && r.ok) {
    $("dServer").className = "dot ok";
    $("server").textContent = "çalışıyor";
    $("dModel").className = "dot " + (r.llm ? "ok" : "off");
    $("model").textContent = r.llm ? r.model : "kapalı";
  } else {
    $("dServer").className = "dot off";
    $("server").textContent = "kapalı";
    $("model").textContent = "—";
    $("warn").hidden = false;
  }
});
