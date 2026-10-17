"""Katman 1b: yaygın Türkçe adlar ve isim tespitinde kullanılan yardımcı listeler.

Liste bilerek küçük tutuldu (~150 ad). Listede olmayan adları Gemma katmanı yakalar.
"""


def tr_lower(s: str) -> str:
    """Türkçe kurallarına uygun küçük harfe çevirme (I→ı, İ→i)."""
    return s.replace("I", "ı").replace("İ", "i").lower()


_ERKEK = """
ahmet mehmet mustafa ali hüseyin hasan ibrahim ismail osman yusuf murat ömer
ramazan halil süleyman abdullah mahmut recep salih kemal fatih emre burak
serkan hakan kadir yasin orhan erkan volkan gökhan cem tolga onur oğuz selim
sinan tuncay levent kenan metin cengiz erdem kerem berk arda efe eren kaan
mert emir furkan enes yiğit batuhan doğan tamer uğur sercan özgür caner engin
adem bayram cemal erol nihat yunus zafer serdar ilker taner barış umut deniz
can muhammed muhammet ahmed mehmed safa yiğit eyüp eyup hamza bilal talha
ömer faruk abdurrahman abdulkadir şükrü ferhat fırat cihan alper koray tuncay
erkan sefa samet semih tayfun hüsnü necati rıza şahin tarık hakkı şevket
"""

_KADIN = """
ayşe fatma emine hatice zeynep elif meryem şerife sultan zehra hanife merve
özlem esra hülya yasemin sevgi melek büşra derya ebru gizem tuğba sibel dilek
filiz gamze aslı burcu pınar seda gülsüm leyla nesrin songül sevim aynur canan
nurcan selin ece irem damla buse cansu ceren defne ela nil sude tuana yağmur
kübra rabia sema şule tülay yeliz neslihan hande gül nur bahar dilara azra
esma havva hacer saadet nazlı gülşen sinem özge tuba esin şeyma beyza
"""

FIRST_NAMES: frozenset[str] = frozenset((_ERKEK + _KADIN).split())

# Tek başına (soyadı veya hitap olmadan) geçtiğinde yaygın kelime de olabilen adlar.
# Bunlar ancak arkasından soyadı ya da hitap gelirse kişi sayılır.
AMBIGUOUS: frozenset[str] = frozenset(
    "can umut deniz barış gül nur bahar yağmur ela nil efe doğan kader ümit".split()
)

# İsmin arkasından gelen ama maskelenmeyen hitaplar ("Ayşe Hanım" → "[KISI_1] Hanım").
HONORIFICS: frozenset[str] = frozenset(
    "hanım bey hoca hocam abla abi ağabey amca teyze dayı usta efendi".split()
)

# Büyük harfle başlasa da soyadı sayılmaması gereken kelimeler.
NOT_SURNAME: frozenset[str] = HONORIFICS | frozenset(
    """
    mahallesi mahalle mah cad caddesi sokak sok sk bulvarı blv no daire kat apt
    apartmanı sitesi köyü tc iban vkn telefon tel e-posta eposta adres adresi
    müşteri müşterimiz sayın sipariş fatura kart ocak şubat mart nisan mayıs
    haziran temmuz ağustos eylül ekim kasım aralık pazartesi salı çarşamba
    perşembe cuma cumartesi pazar ve ile da de ki için ama fakat bu şu o
    kendisi iade bugün yarın dün
    """.split()
)
