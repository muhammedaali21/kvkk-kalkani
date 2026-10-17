"""100 sentetik Türkçe örnek üretir (müşteri hizmetleri, İK, hukuk, karışık, tuzak).

Gerçek kişi verisi YOKTUR. TC/IBAN/VKN/kart numaraları algoritmik olarak geçerli ama rastgele üretilmiştir.
Ad havuzunun bir kısmı bilerek motorun isim listesinde yoktur (dürüst ölçüm için).

Çalıştırma: python benchmark/generate.py  →  benchmark/data.jsonl
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

rng = random.Random(2026)

# --------------------------------------------------------------------------- havuzlar

FIRST = [
    # Motorun listesinde olanlar
    "Ahmet", "Mehmet", "Ayşe", "Fatma", "Zeynep", "Mustafa", "Elif", "Emre", "Merve", "Burak",
    "Selin", "Kerem", "Esra", "Hakan", "Derya", "Onur", "Gizem", "Serkan", "Büşra", "Murat",
    # Motorun listesinde OLMAYANLAR
    "Berkay", "Ilgın", "Doruk", "Eylül", "Çağan", "Nehir", "Begüm", "Koray", "Atakan", "Simge",
    "Ozan", "İlayda", "Taylan", "Melis", "Arda", "Göksel",
]
SURNAMES = [
    "Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Yıldız", "Öztürk", "Aydın", "Arslan", "Doğan",
    "Kılıç", "Aslan", "Çetin", "Kara", "Koç", "Kurt", "Özdemir", "Polat", "Aksoy", "Güneş", "Bulut",
]
MAHALLE = ["Cumhuriyet", "Atatürk", "Yeni", "Fatih", "İstiklal", "Bahçelievler", "Esentepe", "Rızaiye", "Olgunlar"]
SOKAK = ["Gazi Cad.", "Lale Sokak", "Menekşe Sk.", "İnönü Caddesi", "1453. Sokak", "Barış Bulvarı", "Çınar Sok."]
SEHIR = ["Elazığ", "Ankara", "İzmir", "Bursa", "Malatya", "Kayseri", "Antalya"]
ILCE = ["Merkez", "Çankaya", "Karşıyaka", "Nilüfer", "Battalgazi", "Talas", "Muratpaşa"]
SAGLIK = ["şeker hastası", "kemoterapi görüyor", "depresyon tedavisi alıyor", "8 haftalık hamile",
          "epilepsi hastası", "kalp ameliyatı oldu", "panik atak tanısı aldı"]
DIN = ["Alevi olduğu için", "namaz kıldığı için", "Hristiyan olduğunu söyledi", "oruç tuttuğu için"]
SIYASI = ["bir siyasi partinin il yöneticisi", "parti üyesi olduğunu", "siyasi görüşü nedeniyle"]
SENDIKA = ["sendika üyesi", "sendika temsilcisi seçildi", "sendikaya üye olduğu için"]
CEZA = ["dolandırıcılıktan sabıkası var", "hapis cezası almış", "adli sicil kaydı var"]
SIR = ["kâr marjımız %18", "gizli indirim oranı %22", "brüt maaşı 64.500 TL", "teklif üst sınırımız 850.000 TL",
       "maliyetimiz birim başı 37 TL", "bu müşteriye özel iskonto %30"]


def tc() -> str:
    d = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(8)]
    d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    d.append(d10)
    d.append(sum(d) % 10)
    return "".join(map(str, d))


def invalid_11() -> str:
    while True:
        s = str(rng.randint(10**10, 10**11 - 1))
        d = [int(c) for c in s]
        d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
        if d[9] != d10:
            return s


def iban() -> str:
    bban = f"{rng.randint(0, 99999):05d}0{rng.randint(0, 10**16 - 1):016d}"
    num = int("".join(str(int(c, 36)) for c in bban + "TR00"))
    s = f"TR{98 - num % 97:02d}{bban}"
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4)) if rng.random() < 0.7 else s


def vkn() -> str:
    while True:
        d = [rng.randint(0, 9) for _ in range(9)]
        total = 0
        for i in range(1, 10):
            t = (d[i - 1] + 10 - i) % 10
            total += 9 if t == 9 else (t * 2 ** (10 - i)) % 9
        s = "".join(map(str, d)) + str((10 - total % 10) % 10)
        if s[0] != "0":
            return s


def card() -> str:
    d = [rng.choice([4, 5])] + [rng.randint(0, 9) for _ in range(14)]
    total = 0
    for i, x in enumerate(reversed(d)):
        if i % 2 == 0:
            x *= 2
            x -= 9 if x > 9 else 0
        total += x
    d.append((10 - total % 10) % 10)
    s = "".join(map(str, d))
    return " ".join(s[i:i + 4] for i in range(0, 16, 4))


def phone() -> str:
    a, b, c, e = rng.randint(30, 59), rng.randint(100, 999), rng.randint(10, 99), rng.randint(10, 99)
    return rng.choice([f"05{a} {b} {c} {e}", f"+90 5{a} {b} {c} {e}", f"05{a}{b}{c}{e}", f"0(212) {b} {c} {e}"])


ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def email(name: str) -> str:
    first, *rest = name.lower().translate(ASCII).split()
    return f"{first}.{rest[0] if rest else 'x'}{rng.choice(['', str(rng.randint(1, 99))])}@" + rng.choice(
        ["gmail.com", "hotmail.com", "ornekfirma.com.tr", "outlook.com"])


def address() -> str:
    no = rng.randint(1, 120)
    return rng.choice([
        f"{rng.choice(MAHALLE)} Mahallesi {rng.choice(SOKAK)} No: {no} {rng.choice(SEHIR)}",
        f"{rng.choice(MAHALLE)} Mah. {rng.choice(SOKAK)} No:{no}/{rng.randint(1, 20)} {rng.choice(ILCE)}/{rng.choice(SEHIR)}",
        f"{rng.choice(SOKAK)} No: {no} Daire {rng.randint(1, 30)}",
    ])


def plate() -> str:
    return f"{rng.randint(1, 81):02d} {''.join(rng.choice('ABCDEFGHKLMNPRSTUVYZ') for _ in range(rng.choice([2, 3])))} {rng.randint(10, 999)}"


def fix_plate(p: str) -> str:
    code, letters, num = p.split()
    need = {1: 4, 2: 3, 3: 2}[len(letters)]
    return f"{code} {letters} {num.zfill(need)[:4]}"


def person() -> str:
    return f"{rng.choice(FIRST)} {rng.choice(SURNAMES)}"


# --------------------------------------------------------------------------- şablonlar

TEMPLATES = {
    "musteri": [
        "Müşterimiz {KISI} (TC: {TC}) iade istiyor. Telefon {TEL}, e-posta {EPOSTA}. İade {IBAN} IBAN'ına yapılacak. Sipariş no {SIPARIS}.",
        "{KISI} aradı, kargosu gelmemiş. Adresi {ADRES}. Cep: {TEL}. Kendisine nazik bir özür e-postası yaz.",
        "Şikayet: {KISI} kartından ({KART}) iki kez çekim yapılmış. Fatura tarihi {TARIH}, tutar {TUTAR}.",
        "Kurye {AD} Bey {PLAKA} plakalı araçla {SEHIR} deposundan çıktı. Alıcı {KISI}, {TEL}.",
        "Müşteri {KISI} {SAGLIK}, bu yüzden teslimatı kapıya istiyor. Adres: {ADRES}.",
    ],
    "ik": [
        "Performans notu: {KISI}, muhasebe. {SIR}. Geçen ay {SAGLIK}, iki hafta raporluydu.",
        "{KISI} {SENDIKA}; yöneticisi {KISI} bu yüzden terfiye karşı. İletişim: {EPOSTA}.",
        "Yeni çalışan {KISI}, TC {TC}, maaş hesabı {IBAN}. İşe başlama {TARIH}.",
        "İzin talebi: {KISI} {DIN} bayramda izin istiyor. Telefonu {TEL}.",
        "Mülakat notu: aday {KISI} {CEZA}. Referansı {KISI} ({TEL}).",
    ],
    "hukuk": [
        "Müvekkilimiz {KISI} (TC {TC}) aleyhine açılan davada karşı taraf VKN: {VKN}. {SIR}.",
        "Tanık {KISI} {CEZA}; ifadesi {TARIH} tarihinde alındı. Adresi {ADRES}.",
        "Kira sözleşmesi: kiracı {KISI}, {ADRES}. Depozito {IBAN} hesabına yatırıldı.",
        "İşçi {KISI} {SIYASI} gerekçesiyle işten çıkarıldığını iddia ediyor. Vekili {KISI}, {EPOSTA}.",
    ],
    "karisik": [
        "{AD} Hanım'ın notu: {KISI} için fatura kesilecek, vergi numarası {VKN}. {SIR}.",
        "Toplantı özeti — katılanlar: {KISI}, {KISI}, {KISI}. Bütçe {TUTAR}. {SIR}.",
        "{KISI} ({EPOSTA}) yeni teklifi istedi. {SIR}. Kartı {KART} ile ödeme yapacak.",
        "Araç {PLAKA} servise gitti, sahibi {KISI}, {TEL}. Kendisi {SAGLIK}.",
    ],
    "tuzak": [
        "Sipariş no {SIPARIS} {TARIH} tarihinde {SEHIR} deposundan çıktı. Tutar {TUTAR}.",
        "Fatura no {SIPARIS}, ürün kodu SKU-{KOD}, {SEHIR} şubesi. Toplam {TUTAR}.",
        "Kampanya {TARIH} ile {TARIH} arasında geçerli. Umut verici sonuçlar aldık, Deniz manzaralı otel için {TUTAR} ayrıldı.",
        "Takip numarası {SIPARIS}. Müşteri hizmetleri {SEHIR} ve {SEHIR} bölgelerinde açık.",
    ],
}

GOLD = {
    "KISI": ("KISI", person), "AD": ("KISI", lambda: rng.choice(FIRST)), "TC": ("TC", tc),
    "IBAN": ("IBAN", iban), "TEL": ("TELEFON", phone), "ADRES": ("ADRES", address),
    "PLAKA": ("PLAKA", lambda: fix_plate(plate())), "KART": ("KART", card), "VKN": ("VKN", vkn),
    "SAGLIK": ("SAGLIK", lambda: rng.choice(SAGLIK)), "DIN": ("DIN_INANC", lambda: rng.choice(DIN)),
    "SIYASI": ("SIYASI", lambda: rng.choice(SIYASI)), "SENDIKA": ("SENDIKA", lambda: rng.choice(SENDIKA)),
    "CEZA": ("CEZA", lambda: rng.choice(CEZA)), "SIR": ("TICARI_SIR", lambda: rng.choice(SIR)),
}
TRAP = {
    "SIPARIS": invalid_11, "SEHIR": lambda: rng.choice(SEHIR),
    "TARIH": lambda: f"{rng.randint(1, 28):02d}.{rng.randint(1, 12):02d}.2026",
    "TUTAR": lambda: f"{rng.randint(1, 999)}.{rng.randint(100, 999)},00 TL",
    "KOD": lambda: str(rng.randint(10000, 99999)),
}


def render(template: str) -> dict:
    text, spans, pos, last_person = "", [], 0, None
    for m in re.finditer(r"\{(\w+)\}", template):
        text += template[pos:m.start()]
        key = m.group(1)
        if key == "EPOSTA":
            value, typ = email(last_person or person()), "EPOSTA"
        elif key in GOLD:
            typ, gen = GOLD[key]
            value = gen()
            if key == "KISI":
                last_person = value
        else:
            value, typ = TRAP[key](), None
        if typ:
            spans.append({"start": len(text), "end": len(text) + len(value), "type": typ, "value": value})
        text += value
        pos = m.end()
    text += template[pos:]
    return {"text": text, "gold": spans}


def main() -> None:
    out = Path(__file__).with_name("data.jsonl")
    rows = []
    for category, templates in TEMPLATES.items():
        for i in range(20):
            row = render(templates[i % len(templates)])
            row["id"] = f"{category}-{i + 1:02d}"
            row["category"] = category
            rows.append(row)
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    n_gold = sum(len(r["gold"]) for r in rows)
    print(f"{len(rows)} örnek, {n_gold} altın bulgu → {out}")


if __name__ == "__main__":
    main()
