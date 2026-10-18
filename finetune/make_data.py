"""LoRA ince ayarı için sentetik Türkçe eğitim verisi üretir.

Benchmark'tan AYRIDIR: şablonlar tamamen farklıdır, ifade havuzları farklıdır ve rastgele tohum farklıdır.
Böylece benchmark ezberi değil genellemeyi ölçer. Gerçek kişi verisi yoktur; numaralar algoritmik olarak
geçerli ama rastgeledir.

Hedef çıktı, Kalkan'ın Gemma katmanına verdiği talimatla birebir aynı biçimdedir:
{"bulgular": [{"tur": "...", "ifade": "..."}]}. Numaralar (TC, IBAN, telefon, e-posta) hedefte YOKTUR;
talimat onları listelememeyi söyler. Tutarlar, tarihler, şehirler, "maaş hesabı" gibi zararsız ifadeler de
hedefte yoktur (negatif örnekler).

Çalıştırma: python finetune/make_data.py  →  finetune/data/train.jsonl, finetune/data/valid.jsonl
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "benchmark"))

from kalkan.llm import SYSTEM_PROMPT  # noqa: E402
import generate as g  # noqa: E402  (yalnızca numara üreticileri kullanılır)

rng = random.Random(7331)
g.rng = rng

FIRST = ["Hakan", "Cansu", "Tolga", "Damla", "Volkan", "Irmak", "Sinan", "Pelin", "Caner", "Ezgi", "Barış",
         "Gülay", "Oğuzhan", "Serap", "Kadir", "Aslıhan", "Yusuf", "Bengisu", "Rıza", "Nihan", "Alper",
         "Duygu", "Erdem", "Sevda", "Taner", "Zehra", "Ufuk", "Nazlı", "Cengiz", "Hilal", "Kaan", "Feride"]
SUR = ["Karaca", "Bozkurt", "Erdem", "Tekin", "Ünal", "Sarı", "Avcı", "Keskin", "Korkmaz", "Özkan", "Yavuz",
       "Bayram", "Aktaş", "Uçar", "Turan", "Sönmez", "Ateş", "Işık", "Duman", "Gündoğdu", "Kalkan", "Şimşek"]
HONOR = ["Bey", "Hanım", "Hoca"]
MAH = ["Kazım Karabekir", "Mimar Sinan", "Gültepe", "Yunus Emre", "Sakarya", "Mevlana", "Hürriyet"]
SOK = ["Papatya Sokak", "Gül Sk.", "Zafer Caddesi", "Ergenekon Cad.", "Okul Sokak", "Pınar Sk."]
ILCE = ["Kadıköy", "Keçiören", "Bornova", "Osmangazi", "Seyhan", "Meram", "Pamukkale"]
IL = ["İstanbul", "Ankara", "İzmir", "Bursa", "Adana", "Konya", "Denizli"]

# v2: ifadeler kısa ve kesin (yalnızca hassas kısım). v1'de uzun yan cümleler vardı; model uzun aralık vermeyi
# öğrenmişti ("Sendika üyesi olduğu için yöneticisi Kerem Aksoy çekinceli" gibi).
SAGLIK = ["diyabet hastası", "astım tedavisi", "bipolar bozukluk tanısı", "6 aylık hamile", "işitme engelli",
          "migren ilacı kullanıyor", "kanser tedavisi", "tansiyon hastası", "fizik tedavi görüyor",
          "anksiyete bozukluğu", "böbrek nakli oldu", "insülin kullanıyor", "ameliyat oldu"]
DIN = ["Alevi", "Yehova Şahidi", "oruç tutuyor", "Süryani", "namaz kılıyor", "Hristiyan"]
SIYASI = ["parti üyesi", "aday adayı oldu", "partinin gençlik kolu başkanı", "siyasi görüşü"]
SENDIKA = ["sendika üyesi", "sendika temsilcisi", "sendikaya üye oldu", "sendika baş temsilcisi"]
CEZA = ["hırsızlıktan hükümlü", "denetimli serbestlik altında", "sabıka kaydı var", "ceza davası sürüyor",
        "hapis cezası almış"]
SIR = ["birim maliyetimiz 42 TL", "teklif alt sınırımız 1,2 milyon TL", "net kâr marjımız %22",
       "gizli iade primi %7", "maaşı 310.000 TL", "özel indirim oranı %18", "gizli zam oranı %12",
       "ihale fiyatımız 4,8 milyon TL"]
KURUM_KISI = ["muhasebedeki tek erkek çalışan", "genel müdürün eşi", "depo şefinin oğlu", "üçüncü kattaki stajyer"]

# Zararsız ifadeler (negatif örnekler): hedef çıktıda yer almazlar.
NEG = ["fatura tutarı 12.450,00 TL", "toplam bütçe 85.000 TL", "maaş hesabı", "kargo bedeli 49,90 TL",
       "kampanya 15 Kasım'da başlıyor", "Ankara şubesi", "ürün kodu A-2231", "toplantı saat 14:00'te",
       "sipariş tutarı 3.200 TL", "yıllık izin 14 gün", "iade süresi 14 gün", "liste fiyatı 899 TL"]
# Zararsız iş fiilleri: v1 modeli "iade istiyor" ifadesini ticari bilgi sanmıştı.
VERB = ["ürünü iade etmek istiyor", "sipariş durumunu sordu", "fatura talep etti", "kargo takip numarasını istedi",
        "toplantıyı ertelemek istiyor", "adres değişikliği bildirdi", "teklif istedi", "şikâyetini geri çekti",
        "ödeme planı sordu", "randevu almak istiyor", "iade onayı bekliyor", "değişim talep etti"]


def person() -> str:
    return f"{rng.choice(FIRST)} {rng.choice(SUR)}"


def address() -> str:
    return rng.choice([
        f"{rng.choice(MAH)} Mahallesi {rng.choice(SOK)} No: {rng.randint(1, 90)} {rng.choice(ILCE)}/{rng.choice(IL)}",
        f"{rng.choice(SOK)} No:{rng.randint(1, 60)}/{rng.randint(1, 12)} {rng.choice(ILCE)}",
    ])


# {KISI} {AD} {ADRES} {SAGLIK} ... gold; {TC} {IBAN} {TEL} {EPOSTA} {NEG} hedefte yok.
TEMPLATES = [
    "Bankamız müşterisi {KISI} kredi kartı borcunu yapılandırmak istiyor. TC {TC}, iletişim {TEL}. Kendisi {SAGLIK}.",
    "Poliçe sahibi {KISI}, {SAGLIK}; hasar dosyası için {EPOSTA} adresine dönüş yapılacak. {NEG}.",
    "Sınıf öğretmeni notu: öğrencinin velisi {KISI} {DIN}, bu yüzden geziye katılmayacak.",
    "Kargo {ADRES} adresine teslim edilemedi, alıcı {KISI} telefonu {TEL} açmıyor. {NEG}.",
    "İnsan kaynakları: {KISI} {SENDIKA}. {SIR}. Görüşme {AD} {HONOR} ile yapılacak.",
    "Avukatlık bürosu notu: müvekkil {KISI} {CEZA}. Karşı tarafın vekili {KISI}. {NEG}.",
    "E-ticaret destek: {KISI} iade istedi, IBAN {IBAN}. {NEG}. Müşteri {SAGLIK}.",
    "Toplantı notu: {SIR}. Bu bilgiyi {KURUM} ile paylaşmayın.",
    "{AD} {HONOR} aradı, {SIYASI} olduğu için basın açıklamasına katılmayacakmış.",
    "Bordro sorusu: {KISI} {NEG} ile ilgili soru sordu. {SIR}.",
    "Yeni tedarikçi görüşmesi: {SIR}. Sorumlu {KISI}, e-posta {EPOSTA}.",
    "Okul aile birliği: {KISI} {SAGLIK}, ders muafiyeti istiyor. Adres: {ADRES}.",
    "Şikâyet kaydı: {KISI}, {ADRES}. Siparişi gecikmiş. {NEG}.",
    "Personel dosyası: {KURUM} {CEZA}; yönetim kurulu bilgilendirilmedi.",
    "Hasta randevusu: {KISI} {SAGLIK}, kontrol için {NEG}.",
    "Müşteri temsilcisi notu: {AD} {HONOR} {DIN}, cuma günü toplantı istemiyor.",
    "Kampanya raporu: {NEG}, {NEG}. Geçen yıla göre artış var.",
    "Bütçe toplantısı: {NEG}. Kararlar haftaya netleşecek.",
    "Satış ekibi: {SIR}. Bölge müdürü {KISI} onayladı.",
    "Kiracı {KISI} {ADRES} adresindeki daireden taşınıyor, depozito {IBAN} hesabına iade edilecek.",
    "Mülakat: aday {KISI} {SIYASI}; referansı {KISI}, {TEL}.",
    "Sendika yazısı: {KISI} {SENDIKA}, işten çıkarılma itirazı var. {NEG}.",
    "Teklif hazırlığı: {SIR}. Müşteri tarafında muhatap {AD} {HONOR}.",
    "Depo notu: {KURUM} {SAGLIK}, ağır kaldıramıyor.",
    "Sözleşme taslağı: kiracı {KISI} (TC {TC}), {ADRES}. {NEG}.",
    "Çağrı merkezi: {AD} {HONOR} {CEZA} olduğunu söyleyip kimlik doğrulamayı reddetti.",
    "{NEG}. {NEG}. Lütfen raporu güncelleyin.",
    "Eğitim kaydı: öğrenci {KISI}, veli {KISI}, {TEL}. Öğrenci {SAGLIK}.",
    # v2: isim ve hassas bilgi aynı cümlede — ayrı ayrı verilmeli
    "{KISI} {SENDIKA} olduğu için yöneticisi {KISI} çekinceli.",
    "{KISI} {SAGLIK} olduğundan {AD} {HONOR} onun yerine nöbet tutacak.",
    "Avukat notu: {KISI} {CEZA}; tanık {KISI} ifade verecek.",
    "{KISI} {DIN} olduğunu söyledi, {AD} {HONOR} vardiyayı değiştirdi.",
    "{KISI} {SIYASI} olarak biliniyor; {KISI} bunu toplantıda dile getirdi.",
    "Teklif notu: {SIR}. Görüşmeyi {KISI} yürütecek, {KISI} onaylayacak.",
]

# v2: kısa ve zararsız iş mesajları — yalnızca isimler hedefte.
SHORT = [
    "Firmamızın müşterisi {KISI} {VERB}.", "{KISI} {VERB}.", "{AD} {HONOR} {VERB}.", "Abonemiz {KISI} {VERB}, {TEL}.",
    "{KISI} {VERB}; {NEG}.", "Bugün {KISI} aradı, {VERB}.", "{KISI} (TC {TC}) {VERB}.",
]
# v2: hiç hassas veri içermeyen mesajlar — hedef boş liste.
EMPTY = [
    "Siparişin iadesi onaylandı, {NEG}.", "Kargo yarın teslim edilecek; {NEG}.", "{NEG}. Raporu cuma gönderiyorum.",
    "Kullanıcı {VERB}, sistemde kaydı açıldı.", "Toplantı notu: {NEG}, {NEG}.", "Kampanya için {NEG}; görseller hazır.",
    "Bu hafta {NEG}. Ekip toplantısı pazartesi.",
]

GOLD = {
    "KISI": ("KISI", person), "AD": ("KISI", lambda: rng.choice(FIRST)), "ADRES": ("ADRES", address),
    "SAGLIK": ("SAGLIK", lambda: rng.choice(SAGLIK)), "DIN": ("DIN_INANC", lambda: rng.choice(DIN)),
    "SIYASI": ("SIYASI", lambda: rng.choice(SIYASI)), "SENDIKA": ("SENDIKA", lambda: rng.choice(SENDIKA)),
    "CEZA": ("CEZA", lambda: rng.choice(CEZA)), "SIR": ("TICARI_SIR", lambda: rng.choice(SIR)),
    "KURUM": ("KURUM_KISI", lambda: rng.choice(KURUM_KISI)),
}
PLAIN = {
    "TC": g.tc, "IBAN": g.iban, "TEL": g.phone, "EPOSTA": lambda: g.email(person()),
    "NEG": lambda: rng.choice(NEG), "HONOR": lambda: rng.choice(HONOR), "VERB": lambda: rng.choice(VERB),
}


def render(template: str) -> tuple[str, list[dict]]:
    text, gold, pos = "", [], 0
    for m in re.finditer(r"\{(\w+)\}", template):
        text += template[pos:m.start()]
        key = m.group(1)
        if key in GOLD:
            typ, gen = GOLD[key]
            value = gen()
            gold.append({"tur": typ, "ifade": value})
        else:
            value = PLAIN[key]()
        text += value
        pos = m.end()
    text += template[pos:]
    # Aynı ifade birden çok kez geçerse hedefte bir kez yer alır.
    seen, uniq = set(), []
    for item in gold:
        k = (item["tur"], item["ifade"])
        if k not in seen:
            seen.add(k)
            uniq.append(item)
    return text, uniq


def example(template: str) -> dict:
    text, gold = render(template)
    return {"messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
        {"role": "assistant", "content": json.dumps({"bulgular": gold}, ensure_ascii=False)},
    ]}


def pick_template(i: int) -> str:
    # %60 zengin şablon, %25 kısa iş mesajı, %15 hiç hassas veri yok
    r = i % 20
    if r < 12:
        return TEMPLATES[(i // 20 * 12 + r) % len(TEMPLATES)]
    if r < 17:
        return SHORT[(i // 20 * 5 + r) % len(SHORT)]
    return EMPTY[(i // 20 * 3 + r) % len(EMPTY)]


def main(n_train: int = 1600, n_valid: int = 160) -> None:
    out = Path(__file__).with_name("data")
    out.mkdir(exist_ok=True)
    for name, n in (("train", n_train), ("valid", n_valid)):
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for i in range(n):
                f.write(json.dumps(example(pick_template(i)), ensure_ascii=False) + "\n")
    bench = (ROOT / "benchmark" / "data.jsonl").read_text(encoding="utf-8")
    sample = json.loads((out / "train.jsonl").read_text(encoding="utf-8").splitlines()[0])
    print(f"train={n_train}, valid={n_valid} → {out}")
    print("örnek:", sample["messages"][1]["content"])
    print("hedef:", sample["messages"][2]["content"])
    # Sızıntı kontrolü: eğitim cümleleri benchmark'ta geçmemeli.
    overlap = sum(1 for t in TEMPLATES + SHORT + EMPTY if t.split("{")[0].strip() and t.split("{")[0].strip() in bench)
    rows = [json.loads(line) for line in (out / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    empty = sum(1 for r in rows if r["messages"][2]["content"] == '{"bulgular": []}')
    print(f"boş hedefli örnek: {empty} / {len(rows)}")
    print("benchmark ile ortak şablon başlangıcı:", overlap)


if __name__ == "__main__":
    main()
