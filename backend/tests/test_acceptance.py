"""Kabul testi. Çalıştırma: backend klasöründe `python -m pytest tests` veya `python tests/test_acceptance.py`.

Tüm veriler uydurmadır; TC/IBAN algoritmik olarak geçerli ama kimseye ait değildir.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kalkan import llm  # noqa: E402
from kalkan.detectors import iban_valid, luhn_valid, tc_valid, vkn_valid  # noqa: E402
from kalkan.engine import Engine  # noqa: E402

ORNEK = (
    "Müşterimiz Ahmet Yılmaz (TC: 12345678950) iade istiyor. Telefon 0532 123 45 67,\n"
    "e-posta ahmet.yilmaz@gmail.com. İade TR18 0006 2001 1900 0006 6723 15 IBAN'ına.\n"
    "Adresi Cumhuriyet Mahallesi Gazi Cad. No: 12 Elazığ. Ayşe Hanım aradı.\n"
    "Sipariş no 12345678901. Kendisi şeker hastası; kâr marjımız %18."
)


def _engine() -> Engine:
    return Engine(Path(tempfile.mkdtemp()))


def test_validators():
    assert tc_valid("12345678950")
    assert not tc_valid("12345678901")
    assert iban_valid("TR18 0006 2001 1900 0006 6723 15")
    assert not iban_valid("TR18 0006 2001 1900 0006 6723 16")
    assert luhn_valid("4111 1111 1111 1111")
    assert not luhn_valid("4111 1111 1111 1112")
    assert vkn_valid("4840847211")
    assert not vkn_valid("4840847212")


def test_acceptance_regex_layer():
    e = _engine()
    r = e.mask(ORNEK, session="t", use_llm=False)
    masked, by_type = r["masked"], {}
    for f in r["findings"]:
        by_type.setdefault(f["type"], []).append(f["value"])

    assert by_type["TC"] == ["12345678950"]
    assert by_type["IBAN"] == ["TR18 0006 2001 1900 0006 6723 15"]
    assert by_type["TELEFON"] == ["0532 123 45 67"]
    assert by_type["EPOSTA"] == ["ahmet.yilmaz@gmail.com"]
    assert by_type["ADRES"] == ["Cumhuriyet Mahallesi Gazi Cad. No: 12 Elazığ"]
    assert by_type["KISI"] == ["Ahmet Yılmaz", "Ayşe"]
    assert "12345678901" in masked, "sipariş no maskelenmemeli"
    assert "[KISI_2] Hanım" in masked
    for raw in ("Ahmet", "12345678950", "0532", "gmail", "TR18", "Cumhuriyet"):
        assert raw not in masked
    assert e.unmask(masked, "t") == ORNEK


def test_roundtrip_and_consistent_tags():
    e = _engine()
    text = "Ahmet Yılmaz aradı. Ahmet Yılmaz yarın tekrar arayacak, numarası 0532 123 45 67."
    r = e.mask(text, session="s", use_llm=False)
    assert r["masked"].count("[KISI_1]") == 2
    assert e.unmask(r["masked"], "s") == text
    # AI cevabındaki etiketler geri çevrilir.
    assert e.unmask("[KISI_1] için iade onaylandı.", "s") == "Ahmet Yılmaz için iade onaylandı."
    # Başka oturumun etiketleri çözülmez.
    assert e.unmask("[KISI_1]", "baska") == "[KISI_1]"


def test_nonbreaking_spaces():
    # Word/PDF/web'den kopyalanan metinlerde boşluklar U+00A0 olabilir; IBAN yine yakalanmalı.
    e = _engine()
    text = "IBAN: TR18 0006 2001 1900 0006 6723 15, Ahmet Yılmaz"
    r = e.mask(text, session="nb", use_llm=False)
    assert "TR18" not in r["masked"] and "Ahmet" not in r["masked"], r["masked"]
    assert e.unmask(r["masked"], "nb") == text


def test_type_filter_and_policy():
    e = _engine()
    # Kişi adları filtre dışı: isim açık kalır, TC yine gizlenir.
    r = e.mask(ORNEK, session="f1", use_llm=False, types=["TC", "IBAN", "TELEFON", "EPOSTA", "ADRES"])
    assert "Ahmet Yılmaz" in r["masked"] and "12345678950" not in r["masked"]
    assert "KISI" in r["excluded"]
    # Boş liste: hiçbir şey gizlenmez.
    assert e.mask(ORNEK, session="f2", use_llm=False, types=[])["masked"] == ORNEK
    # Filtre çakışma çözümünden önce uygulanır: adres kapalıyken adresin içindeki isim yine gizlenir.
    r = e.mask("Ahmet Yılmaz Sokak No: 5", session="f3", use_llm=False, types=["KISI"])
    assert r["masked"].startswith("[KISI_1]"), r["masked"]
    # Şirket politikası, istekte tür listesi yokken geçerlidir.
    e.policy.set(["TC"])
    r = e.mask(ORNEK, session="f4", use_llm=False)
    assert set(r["counts"]) == {"TC"}, r["counts"]


def test_file_review_and_selection():
    # İki adımlı akış: önce incele (dosya değişmez), sonra yalnızca seçilenleri gizle.
    import io as _io
    import docx
    from kalkan.engine import normalize
    from kalkan.files import mask_file

    sample = Path(__file__).resolve().parents[2] / "ornek" / "sozlesme.docx"
    if not sample.exists():
        print("  (ornek/sozlesme.docx yok — python ornek/olustur.py ile üretin; test atlandı)")
        return
    e = _engine()
    found, cache = [], {}
    mask_file(e, "s.docx", sample.read_bytes(), "analiz", False, found=found, phrase_cache=cache, record=False)
    pairs = {(t, v) for t, v in found}
    assert ("TC", "10000000146") in pairs and ("KISI", "Ayşe Demir") in pairs, pairs
    only = {("TC", normalize("TC", "10000000146")), ("KISI", normalize("KISI", "Ayşe Demir"))}
    out, _, rep = mask_file(e, "s.docx", sample.read_bytes(), "secim", False, ["TC", "KISI"], only=only,
                            phrase_cache=cache, record=False)
    d = docx.Document(_io.BytesIO(out))
    text = "\n".join(p.text for p in d.paragraphs) + "\n".join(c.text for t in d.tables for r in t.rows for c in r.cells)
    assert "10000000146" not in text and "Ayşe Demir" not in text  # seçilenler gizli
    assert "Mehmet" in text and "0532 123 45 67" in text  # seçilmeyenler açık
    assert rep["toplam"] == 2, rep


def test_form_fields_and_names_do_not_cross_lines():
    from kalkan.detectors import detect_names
    e = _engine()
    # Resmî belge düzeni (uydurma veri): etiket, ':' ve değer ayrı satırlarda da olabilir.
    split = "Adı\n:\nMUHAMMED SAFA\nSoyadı\n:\nYİĞİT\nBaba Adı\n:\nMAHMUT\nDoğum Tarihi\n:\n23.01.2007\nSosyal Güvenlik Kurumu"
    same = "T.C. Kimlik No : 12345678950\nAdı : MUHAMMED SAFA\nSoyadı : YİĞİT\nDoğum Yeri : BATMAN\nSayı :\nKonu : Tespit\nTarih: 10.10.2026"
    for text in (split, same):
        r = e.mask(text, session="form", use_llm=False)
        got = {(f["type"], f["value"]) for f in r["findings"]}
        assert ("KISI", "MUHAMMED SAFA") in got and ("KISI", "YİĞİT") in got, got
        assert not any("\n" in v for _, v in got), got  # hiçbir değer satır atlamamalı
    assert ("DOGUM_TARIHI", "23.01.2007") in {(f["type"], f["value"]) for f in e.mask(split, session="f", use_llm=False)["findings"]}
    r = e.mask(same, session="g", use_llm=False)
    assert "10.10.2026" in r["masked"] and "Tespit" in r["masked"]  # belge tarihi ve konu gizlenmez
    assert "BATMAN" not in r["masked"]
    # İsim tespiti: "YİĞİT\nBaba" ve "MAHMUT Sosyal" birleştirilmemeli.
    assert all("\n" not in f.value for f in detect_names("Soyadı\nYİĞİT\nBaba Adı\nMAHMUT Sosyal Güvenlik"))
    assert [f.value for f in detect_names("AHMET Yılmaz geldi")] == []  # biçim tutmuyor, tek büyük harfli kelime


def test_official_pdf_sample():
    from kalkan.files import mask_file
    import pymupdf
    sample = Path(__file__).resolve().parents[2] / "ornek" / "resmi_belge.pdf"
    if not sample.exists():
        print("  (ornek/resmi_belge.pdf yok — python ornek/olustur.py ile üretin; test atlandı)")
        return
    e = _engine()
    out, _, rep = mask_file(e, "r.pdf", sample.read_bytes(), "pdf", False, record=False)
    text = "\n".join(p.get_text() for p in pymupdf.open(stream=out, filetype="pdf"))
    for secret in ("12345678950", "MUHAMMED", "YİĞİT", "MAHMUT", "BATMAN", "23.01.2007"):
        assert secret not in text, secret
    assert "10.10.2026" in text and rep["kalan"] == 0


def test_policy_new_types_default_on():
    import json, tempfile as _t
    d = Path(_t.mkdtemp())
    (d / "politika.json").write_text(json.dumps({"turler": ["TC", "KISI"]}), encoding="utf-8")  # eski biçim
    e = Engine(d)
    assert "DOGUM_TARIHI" in e.policy.types and "IBAN" not in e.policy.types


def test_stats_have_no_raw_data():
    e = _engine()
    e.mask(ORNEK, session="x", use_llm=False)
    raw = e.stats.path.read_text(encoding="utf-8")
    for secret in ("Ahmet", "12345678950", "TR18", "gmail"):
        assert secret not in raw


def test_acceptance_gemma_layer():
    if not llm.available():
        print("  (Ollama/Gemma kapalı — Gemma kabul testi atlandı)")
        return
    e = _engine()
    r = e.mask(ORNEK, session="g", use_llm=True)
    types = {f["value"]: f["type"] for f in r["findings"]}
    assert r["llm_used"]
    assert any(t == "SAGLIK" and "şeker hastası" in v for v, t in types.items()), types
    assert any(t == "TICARI_SIR" and "%18" in v for v, t in types.items()), types
    assert "12345678901" in r["masked"]
    assert e.unmask(r["masked"], "g") == ORNEK


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK  {name}")
    print("Tüm kabul testleri geçti.")
