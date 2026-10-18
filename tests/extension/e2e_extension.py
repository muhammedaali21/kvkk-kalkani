"""Eklentinin uçtan uca testi: gerçek Chromium + yüklü eklenti + sahte ChatGPT sayfası.

chatgpt.com istekleri yerel mock_chatgpt.html'e yönlendirilir; eklentinin içerik betiği gerçek
alan adında çalışır. Kalkan sunucusu bu betik tarafından başlatılır ve kapatılır.

Gereksinim: pip install playwright && python -m playwright install chromium
Çalıştırma (proje kökünde): python extension/test/e2e_extension.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
EXT = ROOT / "extension"
MOCK = (Path(__file__).parent / "mock_chatgpt.html").read_text(encoding="utf-8")
API = "http://127.0.0.1:8765"

# Uydurma veri; TC/IBAN algoritmik olarak geçerli ama kimseye ait değil.
MESSAGE_LINES = [
    "Müşterimiz Ahmet Yılmaz (TC: 12345678950) iade istiyor.",
    "IBAN: TR18 0006 2001 1900 0006 6723 15, telefon 0532 123 45 67.",
]
RAW = ["Ahmet", "12345678950", "TR18", "0532"]


def start_server() -> subprocess.Popen:
    if _port_open():
        sys.exit("8765 portunda zaten bir sunucu çalışıyor; test kendi sunucusunu yönetir. Önce onu kapatın.")
    env = {**os.environ, "OLLAMA_URL": os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "kalkan.api:app", "--host", "127.0.0.1", "--port", "8765"],
        cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            httpx.get(f"{API}/health", timeout=5)
            return proc
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("Kalkan sunucusu başlamadı")


def _port_open() -> bool:
    try:
        httpx.get(f"{API}/health", timeout=3)
        return True
    except httpx.HTTPError:
        return False


def type_message(page) -> None:
    ed = page.locator("#prompt-textarea")
    ed.click()
    for i, line in enumerate(MESSAGE_LINES):
        if i:
            page.keyboard.press("Shift+Enter")
            # Sahte editör Shift+Enter'ı işlemediği için satırı elle ekle.
            page.evaluate("document.getElementById('prompt-textarea').appendChild(document.createElement('p'))")
            page.evaluate(
                "() => { const p = document.getElementById('prompt-textarea').lastElementChild;"
                " const r = document.createRange(); r.setStart(p, 0); r.collapse(true);"
                " const s = getSelection(); s.removeAllRanges(); s.addRange(r); }"
            )
        page.keyboard.insert_text(line)


def paste_screenshot(page) -> None:
    """Sayfada uydurma bir ekran görüntüsü çizip editöre yapıştırır."""
    page.evaluate("""async () => {
        const c = document.createElement('canvas'); c.width = 820; c.height = 90;
        const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 820, 90);
        g.fillStyle = '#000'; g.font = '22px Arial';
        g.fillText('Müşteri: Ahmet Yılmaz', 16, 34);
        g.fillText('TC 12345678950   Tel 0532 123 45 67', 16, 70);
        const blob = await new Promise((r) => c.toBlob(r, 'image/png'));
        const dt = new DataTransfer(); dt.items.add(new File([blob], 'ekran.png', { type: 'image/png' }));
        document.getElementById('prompt-textarea').dispatchEvent(
            new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
    }""")


def ocr_data_url(data_url: str) -> str:
    import base64
    import io

    sys.path.insert(0, str(ROOT / "backend"))
    from PIL import Image
    from kalkan.images import ocr

    img = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))
    return ocr(img)[0]


def check_sent(page, n: int) -> str:
    page.wait_for_function(f"window.__sent.length >= {n}", timeout=15000)
    sent = page.evaluate(f"window.__sent[{n - 1}]")
    leaked = [r for r in RAW if r in sent]
    assert not leaked, f"Ham veri siteye gitti: {leaked}\n{sent}"
    assert "[KISI_1]" in sent and "[TC_1]" in sent and "[IBAN_1]" in sent, sent
    assert sent.count("\n") == 1, f"Satır yapısı bozuldu: {sent!r}"
    return sent


def main() -> None:
    server = start_server()
    ok = True
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                tempfile.mkdtemp(), channel="chromium", headless=True,
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"],
            )
            if not ctx.service_workers:
                ctx.wait_for_event("serviceworker", timeout=10000)
            ctx.route("https://chatgpt.com/**", lambda route: route.fulfill(
                status=200, content_type="text/html; charset=utf-8", body=MOCK))
            page = ctx.new_page()
            page.on("pageerror", lambda e: print("SAYFA HATASI", e))
            page.goto("https://chatgpt.com/")
            page.wait_for_timeout(800)

            # 1) Enter ile gönderim
            type_message(page)
            page.keyboard.press("Enter")
            sent = check_sent(page, 1)
            print("OK  Enter: siteye giden metin maskeli →", sent.replace("\n", " ⏎ "))

            # 2) Cevaptaki etiketler ekranda gerçek değerlere döner
            page.wait_for_selector(".assistant-msg[data-done='1']", timeout=10000)
            page.wait_for_function(
                "document.querySelector('.assistant-msg').textContent.includes('Ahmet Yılmaz')", timeout=10000)
            print("OK  Cevap ekranda geri çevrildi →", page.locator(".assistant-msg").inner_text())
            user_bubble = page.locator(".user-msg").first.inner_text()
            assert "Ahmet Yılmaz" in user_bubble, user_bubble
            print("OK  Kullanıcının kendi mesajı da ekranda gerçek değerlerle görünüyor")

            # 3) Gönder düğmesine tıklama
            type_message(page)
            page.locator('[data-testid="send-button"]').click()
            check_sent(page, 2)
            print("OK  Gönder düğmesi: siteye giden metin maskeli")

            # 3b) Ekran görüntüsü yapıştırma: siteye karartılmış görüntü ulaşır
            paste_screenshot(page)
            page.wait_for_function("window.__files.length >= 1", timeout=60000)
            got = page.evaluate("window.__files[0]")
            text = ocr_data_url(got["dataUrl"])
            assert got["name"].endswith("-kalkan.png"), got["name"]
            assert "12345678950" not in text.replace(" ", "") and "Yılmaz" not in text, text
            print("OK  Ekran görüntüsü yapıştırma: siteye karartılmış görüntü ulaştı →", " ".join(text.split())[:80])

            # 3c) Dosya seçme düğmesi (ataç)
            page.set_input_files("#upload", str(ROOT / "ornek" / "ekran_crm.png"))
            page.wait_for_function("window.__files.length >= 2", timeout=60000)
            got = page.evaluate("window.__files[1]")
            text = ocr_data_url(got["dataUrl"])
            assert got["via"] == "input" and got["name"].endswith("-kalkan.png"), got["name"]
            assert "10750985038" not in text.replace(" ", "") and "Elif Demir" not in text, text
            print("OK  Dosya seçme: siteye karartılmış görüntü ulaştı")

            # 4) Sunucu kapalıyken mesaj gönderilmez (güvenli taraf)
            server.kill()
            server.wait()
            assert not _port_open()
            type_message(page)
            page.keyboard.press("Enter")
            page.wait_for_selector(".kvkk-kalkan-toast[data-kind='error']", timeout=10000)
            page.wait_for_timeout(500)
            assert page.evaluate("window.__sent.length") == 2, "Sunucu kapalıyken mesaj gönderildi!"
            print("OK  Sunucu kapalı: mesaj gönderilmedi, kırmızı uyarı →",
                  page.locator(".kvkk-kalkan-toast").inner_text())

            # 4b) Sunucu kapalıyken ekran görüntüsü de eklenmez
            page.evaluate("document.querySelector('.kvkk-kalkan-toast').dataset.kind = 'x'")
            paste_screenshot(page)
            page.wait_for_selector(".kvkk-kalkan-toast[data-kind='error']", timeout=15000)
            page.wait_for_timeout(500)
            assert page.evaluate("window.__files.length") == 2, "Sunucu kapalıyken görüntü eklendi!"
            print("OK  Sunucu kapalı: ekran görüntüsü eklenmedi")
            ctx.close()
    except AssertionError as e:
        ok = False
        print("HATA", e)
    finally:
        server.kill()
    print("Eklenti testi geçti." if ok else "Eklenti testi BAŞARISIZ.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
