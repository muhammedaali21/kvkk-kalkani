"""Dosya maskeleme denemesi için örnek müşteri listesi üretir (ornek/musteriler.xlsx, .csv).

Tüm veriler uydurmadır; TC/IBAN algoritmik olarak geçerli ama kimseye ait değildir.
Çalıştırma: python ornek/olustur.py
"""

import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))
import generate as g  # noqa: E402

g.rng.seed(19)
rng = g.rng

KISILER = ["Ahmet Yılmaz", "Ayşe Demir", "Mehmet Kaya", "Zeynep Çelik", "Berkay Kurt",
           "Elif Aydın", "Doruk Aslan", "Merve Şahin"]
NOTLAR = ["", "", "Kargo gecikti, özür e-postası atılacak.", "Kendisi şeker hastası, kapıya teslim istiyor.",
          "Bu müşteriye özel iskonto %30 uygulanıyor.", "İade talebi var.", "Ahmet Bey'in yönlendirmesiyle geldi."]

satirlar = []
# Aynı müşteri birden fazla sipariş verir: maskeli dosyada da aynı etiketi almalı.
for i in range(16):
    kisi = KISILER[i % len(KISILER)] if i < 8 else rng.choice(KISILER)
    rng_k = random.Random(kisi)  # aynı kişi → aynı TC/telefon/IBAN
    g.rng = rng_k
    tc, tel, iban, mail = g.tc(), g.phone(), g.iban(), g.email(kisi)
    g.rng = rng
    satirlar.append({
        "Sipariş No": g.invalid_11(),
        "Tarih": f"{rng.randint(1, 28):02d}.10.2026",
        "Ad Soyad": kisi,
        "TC Kimlik": tc,
        "Telefon": tel,
        "E-posta": mail,
        "IBAN": iban,
        "Şehir": rng.choice(g.SEHIR),
        "Adet": rng.randint(1, 5),
        "Tutar (TL)": rng.randint(150, 9500),
        "Not": rng.choice(NOTLAR),
    })

df = pd.DataFrame(satirlar)
out = Path(__file__).parent
df.to_excel(out / "musteriler.xlsx", index=False)
df.to_csv(out / "musteriler.csv", index=False, sep=";", encoding="utf-8-sig")
print(df.to_string())
