// KVKK Kalkanı içerik betiği: gönderimi yakalar, metni maskeler, cevaptaki etiketleri ekranda geri çevirir.
(() => {
  const TAG_RE = /\[([A-Z][A-Z_]*_\d+)\]/g;
  const HAS_TAG = /\[[A-Z][A-Z_]*_\d+\]/;
  const EDITABLE = '[contenteditable="true"], textarea';
  const LABELS = {
    TC: "TC", IBAN: "IBAN", KART: "kart", VKN: "vergi no", EPOSTA: "e-posta", TELEFON: "telefon",
    PLAKA: "plaka", ADRES: "adres", KISI: "kişi", KURUM_KISI: "dolaylı kimlik", SAGLIK: "sağlık",
    DIN_INANC: "din/inanç", SIYASI: "siyasi", SENDIKA: "sendika", CEZA: "ceza", BIYOMETRIK: "biyometrik",
    TICARI_SIR: "ticari sır", SOZLUK: "şirket sözlüğü",
  };

  let enabled = true;
  let bypass = false;
  let busy = false;
  let mapping = {};

  chrome.storage.local.get("enabled").then(({ enabled: e }) => (enabled = e !== false));
  chrome.storage.onChanged.addListener((ch) => {
    if (ch.enabled) enabled = ch.enabled.newValue !== false;
    if (ch.session) mapping = {};
  });

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => s.replace(/\s+/g, " ").trim();
  const send = (msg) =>
    new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(msg, (r) => resolve(chrome.runtime.lastError ? null : r));
      } catch {
        resolve(null); // eklenti yeniden yüklendiyse
      }
    });

  // ---------------------------------------------------------------- editör

  function findEditor() {
    return document.querySelector(
      '#prompt-textarea[contenteditable="true"], div.ProseMirror[contenteditable="true"], ' +
        'rich-textarea .ql-editor[contenteditable="true"], div[contenteditable="true"], textarea'
    );
  }

  function findSendButton() {
    return document.querySelector(
      'button[data-testid="send-button"], #composer-submit-button, button[aria-label="Send message" i], ' +
        'button[aria-label="Send Message" i], button.send-button, button[aria-label*="Gönder" i]'
    );
  }

  function isSendButton(btn) {
    if (!btn) return false;
    const label = `${btn.getAttribute("aria-label") || ""} ${btn.getAttribute("data-testid") || ""} ${btn.id}`;
    return /send|gönder|submit/i.test(label) || btn.classList.contains("send-button");
  }

  function getText(ed) {
    if (ed.tagName === "TEXTAREA") return ed.value;
    // ProseMirror/Quill her satırı ayrı <p> olarak tutar; innerText paragraflar arasına fazladan satır ekler.
    const blocks = [...ed.children];
    if (blocks.length && blocks.every((b) => /^(P|DIV)$/.test(b.tagName))) {
      return blocks.map((b) => b.textContent).join("\n");
    }
    return ed.innerText;
  }

  function setText(ed, text) {
    ed.focus();
    if (ed.tagName === "TEXTAREA") {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      setter.call(ed, text);
      ed.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    document.execCommand("selectAll", false, null);
    // Önce yapıştırma olayı dene (satır sonlarını korur), editör işlemezse insertText'e düş.
    const dt = new DataTransfer();
    dt.setData("text/plain", text);
    const paste = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
    ed.dispatchEvent(paste);
    if (!paste.defaultPrevented) document.execCommand("insertText", false, text);
  }

  // ---------------------------------------------------------------- gönderim

  async function protectAndSend(ed, clickedButton) {
    if (busy) return;
    const text = getText(ed);
    if (!text.trim()) return;
    busy = true;
    try {
      toast("Mesaj taranıyor…", "info", 15000);
      const r = await send({ type: "mask", text });
      if (!r || !r.ok) {
        toast(
          "Yerel sunucuya ulaşılamadı; güvenlik gereği mesaj gönderilmedi. " +
            "Sunucuyu başlatın veya eklenti menüsünden korumayı kapatın.",
          "error",
          9000
        );
        return;
      }
      if (r.findings.length) {
        setText(ed, r.masked);
        await sleep(150);
        if (norm(getText(ed)) !== norm(r.masked)) {
          // Editör içeriği değiştirilemediyse ham veriyi göndermektense hiç gönderme.
          await navigator.clipboard.writeText(r.masked).catch(() => {});
          toast("Metin editörde değiştirilemedi; mesaj gönderilmedi. Maskeli metin panoya kopyalandı.", "error", 9000);
          return;
        }
        for (const f of r.findings) mapping[f.tag] = f.value;
        refreshMapping();
        const parts = Object.entries(r.counts).map(([t, n]) => `${n} ${LABELS[t] || t}`);
        const special = r.findings.some((f) => f.special) ? " · KVKK m.6 özel nitelikli veri dahil" : "";
        toast(`${r.findings.length} hassas değer gizlendi: ${parts.join(", ")}${special}`, "ok", 5000);
      } else {
        toast("Hassas veri bulunmadı, mesaj olduğu gibi gönderildi.", "ok", 2000);
      }
      await submit(ed, clickedButton);
    } finally {
      busy = false;
    }
  }

  async function submit(ed, clickedButton) {
    // React'in gönder düğmesini etkinleştirmesini bekle.
    let btn = null;
    for (let i = 0; i < 20; i++) {
      btn = findSendButton() || clickedButton;
      if (btn && !btn.disabled) break;
      await sleep(50);
    }
    // click() ve dispatchEvent senkron çalışır; baypas sadece bu çağrı süresince açık kalır,
    // böylece hemen ardından yazılan mesaj maskelenmeden gidemez.
    bypass = true;
    try {
      if (btn && !btn.disabled) {
        btn.click();
      } else {
        ed.dispatchEvent(
          new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true })
        );
      }
    } finally {
      bypass = false;
    }
  }

  document.addEventListener(
    "keydown",
    (e) => {
      if (!enabled || bypass) return;
      if (e.key !== "Enter" || e.shiftKey || e.altKey || e.isComposing) return;
      const ed = e.target && e.target.closest && e.target.closest(EDITABLE);
      if (!ed || !getText(ed).trim()) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      protectAndSend(ed);
    },
    true
  );

  document.addEventListener(
    "click",
    (e) => {
      if (!enabled || bypass) return;
      const btn = e.target && e.target.closest && e.target.closest("button");
      if (!isSendButton(btn)) return;
      const ed = findEditor();
      if (!ed || !getText(ed).trim()) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      protectAndSend(ed, btn);
    },
    true
  );

  // ---------------------------------------------------------------- geri çevirme

  let mappingInflight = false;
  let mappingAgain = false;
  function refreshMapping() {
    // En fazla saniyede bir sor; bu arada gelen istekleri kaybetme, sonra bir kez daha sor.
    if (mappingInflight) {
      mappingAgain = true;
      return;
    }
    mappingInflight = true;
    send({ type: "mapping" }).then((r) => {
      if (r && r.ok) mapping = { ...mapping, ...r.mapping };
      scheduleScan();
      setTimeout(() => {
        mappingInflight = false;
        if (mappingAgain) {
          mappingAgain = false;
          refreshMapping();
        }
      }, 1000);
    });
  }

  function scan() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        if (!n.nodeValue || !HAS_TAG.test(n.nodeValue)) return NodeFilter.FILTER_REJECT;
        const p = n.parentElement;
        // Editörün içine ve kendi uyarılarımıza dokunma.
        if (!p || p.closest(`${EDITABLE}, input, script, style, .kvkk-kalkan-toast`)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let unknown = false;
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const next = node.nodeValue.replace(TAG_RE, (m) => {
        if (m in mapping) return mapping[m];
        unknown = true;
        return m;
      });
      if (next !== node.nodeValue) node.nodeValue = next;
    }
    if (unknown) refreshMapping();
  }

  let scanPending = false;
  function scheduleScan() {
    if (scanPending) return;
    scanPending = true;
    setTimeout(() => {
      scanPending = false;
      if (enabled) scan();
    }, 200);
  }

  new MutationObserver(scheduleScan).observe(document.body, { childList: true, subtree: true, characterData: true });
  refreshMapping();

  // ---------------------------------------------------------------- uyarı kutusu

  let toastEl = null;
  let toastTimer = null;
  function toast(message, kind = "info", ms = 4000) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "kvkk-kalkan-toast";
      toastEl.setAttribute("role", "status");
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = message;
    toastEl.dataset.kind = kind;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toastEl.hidden = true), ms);
  }
})();
