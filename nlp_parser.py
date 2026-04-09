"""
nlp_parser.py  v3  —  Bilingual NLP (English + Tamil)

Key design decisions:
 - TAMIL_FOOD_MAP maps Tamil/romanised variants → English menu names.
   New items added via admin are auto-appended here by auto_nlp_updater.py.
 - _translate() processes the map LONGEST-ENTRY-FIRST so compound phrases
   like "chicken biryani" are matched before individual words like "chicken".
 - _safe_replace() uses word-boundary regex for ASCII words to prevent
   "dal" inside "sandal" or "podalaam" being corrupted.
 - Numbers work for Tamil script, romanised Tamil, and English words.
"""

import re

# ─────────────────────────────────────────────────────────────────────────────
#  Number words
# ─────────────────────────────────────────────────────────────────────────────
ENGLISH_NUMS = {
    "zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,
    "six":6,"seven":7,"eight":8,"nine":9,"ten":10,
    "eleven":11,"twelve":12,"a":1,"an":1,
}

TAMIL_NUMS = {
    # Tamil script
    "ஒன்று":1,"ஒரு":1,"இரண்டு":2,"மூன்று":3,"நான்கு":4,"ஐந்து":5,
    "ஆறு":6,"ஏழு":7,"எட்டு":8,"ஒன்பது":9,"பத்து":10,"பன்னிரண்டு":12,
    # Romanised (Chrome SR)
    "onnu":1,"onru":1,"oru":1,"rendu":2,"irantu":2,"irandu":2,
    "moonu":3,"naalu":4,"anju":5,"aaru":6,"ezhu":7,"ettu":8,
    "ombodu":9,"pattu":10,"pannirandu":12,
}

# ─────────────────────────────────────────────────────────────────────────────
#  Intent trigger words
# ─────────────────────────────────────────────────────────────────────────────
CONFIRM_EN = ["confirm","place order","done","finish","complete","checkout",
              "yes confirm","submit order","finalize"]
CONFIRM_TA = ["உறுதி","ஆர்டர் கொடு","முடிந்தது","சரி","ஓகே",
              "confirm pannu","confirm panni","order podu","order podungo",
              "confirm seiy","confirm sei"]

CANCEL_EN  = ["cancel","abort","clear order","start over","reset","nevermind","never mind"]
CANCEL_TA  = ["ரத்து","நிறுத்து","cancel pannu","cancel panni","cancel seiy","vendaam","வேண்டாம்"]

REMOVE_EN  = ["remove","delete","take off","don't want","no more","take out","minus"]
REMOVE_TA  = ["நீக்கு","எடு","cancel item","remove pannu","எடுத்துவிடு",
              "neeaku","neekku","neeku","edunga","eduthudu"]

SHOW_EN    = ["show order","my order","view order","show cart","what did i order",
              "list order","show my","what's in my","whats in my"]
SHOW_TA    = ["என் ஆர்டர்","காட்டு","பார்","order பார்","show pannu","list pannu",
              "kaatu","kaatungo","paar","order paar"]

UPDATE_EN  = ["change","update","modify","make it","replace"]
UPDATE_TA  = ["மாற்று","திருத்து","change pannu","maattu","maatungo"]

ADD_HINTS_TA = ["வேண்டும்","வேணும்","வேனும்","தா","தாங்க","தாங்கோ","குடுங்க","குடுங்கோ",
                "kudunga","kudungo","thaa","thaango","vendum","venum","veno",
                "thaan","vango","please add","order pannu","kudu"]

# ─────────────────────────────────────────────────────────────────────────────
#  Tamil → English food map
#  NOTE: auto_nlp_updater.py appends new entries here when items are added.
#  IMPORTANT: keep entries sorted longest-first at runtime (done in _translate).
# ─────────────────────────────────────────────────────────────────────────────
TAMIL_FOOD_MAP = {
    # Idli
    "இட்லி":"idli","idly":"idli",
    # Dosa
    "தோசை":"dosa","dosai":"dosa","dose":"dosa","dhosa":"dosa",
    # Naan
    "நான்":"naan","nan":"naan","naai":"naan","nai":"naan",
    # Roti
    "ரொட்டி":"roti","chapati":"roti","chapathi":"roti","chappati":"roti",
    # Biryani
    "பிரியாணி":"biryani","biriyani":"biryani","briyani":"biryani","biriani":"biryani",
    # Fried rice
    "சாதம்":"fried rice","soru":"fried rice","sadam":"fried rice",
    # Dal tadka
    "தால்":"dal tadka","பருப்பு":"dal tadka","paruppu":"dal tadka",
    "parupu":"dal tadka","parpu":"dal tadka",
    # Paneer butter masala
    "பட்டர் பனீர்":"paneer butter masala","butter paneer":"paneer butter masala",
    "பனீர்":"paneer butter masala","paneer":"paneer butter masala",
    # Chicken curry
    "kozhi curry":"chicken curry","கோழி கறி":"chicken curry",
    "சிக்கன் கறி":"chicken curry","சிக்கன்":"chicken curry",
    "கோழி":"chicken curry","kozhi":"chicken curry","chicken":"chicken curry",
    # Masala chai
    "masala chai":"masala chai","சாய்":"masala chai","டீ":"masala chai",
    "chai":"masala chai","chaai":"masala chai","chay":"masala chai",
    "tea":"masala chai","thaai":"masala chai",
    # Mango lassi
    "மாம்பழ லஸ்சி":"mango lassi","mango lassi":"mango lassi",
    "lassi mango":"mango lassi","லஸ்சி":"mango lassi","lassi":"mango lassi",
    # Samosa
    "சமோசா":"samosa","samoosa":"samosa",
    # Veg soup
    "vegetable soup":"veg soup","வெஜ் சூப்":"veg soup","சூப்":"veg soup",
    "supp":"veg soup","suppuu":"veg soup",
    # Gulab jamun
    "குலாப் ஜாமுன்":"gulab jamun","gulab jamun":"gulab jamun",
    "குலாப்":"gulab jamun","gulab":"gulab jamun","jamun":"gulab jamun",
    # Ice cream
    "ஐஸ்க்ரீம்":"ice cream","ice cream":"ice cream","icecream":"ice cream",
    "ais cream":"ice cream","aiskrim":"ice cream","ice kireem":"ice cream",
    "ais krim":"ice cream","ஐஸ்":"ice cream",

    # ── Puri (auto-added) ──────────────────
    "puri":"puri",
    "பூரி":"puri",
    "poori":"puri",

    # ── Chapaathi (auto-added) ──────────────────
    "chapathi":"chapaathi",

    # ── Vada (auto-added) ──────────────────
    "vada":"vada",

    # ── Mandi (auto-added) ──────────────────
    "mandi":"mandi",

    # ── Mutton Biryani (auto-added) ──────────────────
    "mutton biryani":"mutton biryani",
    "மட்டன் பிரியாணி":"mutton biryani",
    "matton briyani":"mutton biryani",
    "matton biriani":"mutton biryani",
    "mutton biriani":"mutton biryani",
    "mutton briyani":"mutton biryani",
    "matton biryani":"mutton biryani",
    "matton biriyani":"mutton biryani",
    "mutton biriyani":"mutton biryani",

    # ── Mutton (auto-added) ──────────────────
    "mutton":"mutton",
    "மட்டன்":"mutton",
    "matton":"mutton",

    # ── சப்பாத்தி (auto-added) ──────────────────
    "சப்பாத்தி":"chapati",

    # ── Veg Samosa (auto-added) ──────────────────
    "veg samosa":"veg samosa",
    "veg samoosa":"veg samosa",
    "veggie samosa":"veg samosa",
    "veggie samoosa":"veg samosa",

    # ── Veg Samoosa (auto-added) ──────────────────
    "வெஜ் சமோசா":"veg samosa",

    # ── வெஜ் சப்பாத்தி (auto-added) ──────────────────
    "வெஜ் சப்பாத்தி":"veg samosa",

    # ── Veg Meals (auto-added) ──────────────────
    "veg meals":"veg meals",
    "காய்கறி meals":"veg meals",
    "veggie meals":"veg meals",

    # ── One Puri ,Two Puri, Three Puri (auto-added) ──────────────────
    "one puri ,two puri, three puri":"puri",
    "one பூரி two பூரி three பூரி":"puri",
    "one puri two puri three puri":"puri",
    "one puri two puri three poori":"puri",
    "one puri two poori three puri":"puri",
    "one poori two puri three puri":"puri",
    "one poori two puri three poori":"puri",
    "one poori two poori three puri":"puri",
    "one puri two poori three poori":"puri",
    "one poori two poori three poori":"puri",

    # ── Mandhi (auto-added) ──────────────────
    "mandhi":"mandi",

    # ── Manddi (auto-added) ──────────────────
    "manddi":"mandi",

    # ── Parotta (auto-added) ──────────────────
    "parotta":"parotta",
    "பரோட்டா":"parotta",
    "parota":"parotta",
}

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    return re.sub(r'\s+', ' ', text.lower().strip())


def _is_tamil(s: str) -> bool:
    """True if string contains Tamil Unicode characters."""
    return any(ord(c) > 127 for c in s)


def _safe_replace(text: str, old: str, new: str) -> str:
    """
    Replace `old` with `new` in `text`.
    For ASCII words: requires word boundary to avoid partial matches.
    For Tamil script: direct substring replace (no word boundary concept).
    """
    if _is_tamil(old):
        return text.replace(old, new)
    # ASCII word-boundary replacement
    pattern = r'(?<![a-z])' + re.escape(old) + r'(?![a-z])'
    return re.sub(pattern, new, text)


def _translate(text: str) -> str:
    """
    Replace Tamil/romanised food words with their English menu names.

    Uses a protect-and-restore strategy:
      1. Process map LONGEST-key-first.
      2. When a key matches, replace it with a numbered placeholder __F0__, __F1__…
         so its sub-strings can't match again in subsequent iterations.
      3. After all keys are processed, restore placeholders → final English values.

    This ensures "chicken biryani" is locked in before "chicken" alone can fire.
    """
    placeholders = {}   # index → english_value
    idx = 0

    for key, val in sorted(TAMIL_FOOD_MAP.items(), key=lambda x: -len(x[0])):
        if key in text:
            ph = f"__F{idx}__"
            text = _safe_replace(text, key, ph)
            placeholders[ph] = val
            idx += 1

    # Restore all placeholders to their English values
    for ph, val in placeholders.items():
        text = text.replace(ph, val)

    return text


def extract_quantity(text: str) -> int:
    m = re.search(r'\b(\d+)\b', text)
    if m:
        return int(m.group(1))
    for word, num in sorted(TAMIL_NUMS.items(), key=lambda x: -len(x[0])):
        if word in text:
            return num
    for word, num in sorted(ENGLISH_NUMS.items(), key=lambda x: -len(x[0])):
        if re.search(r'(?<![a-z])' + re.escape(word) + r'(?![a-z])', text):
            return num
    return 1


def extract_intent(text: str) -> str:
    t = _normalise(text)
    if any(w in t for w in CONFIRM_EN + CONFIRM_TA): return "CONFIRM"
    if any(w in t for w in CANCEL_EN  + CANCEL_TA):  return "CANCEL"
    if any(w in t for w in REMOVE_EN  + REMOVE_TA):  return "REMOVE"
    if any(w in t for w in SHOW_EN    + SHOW_TA):     return "SHOW"
    if any(w in t for w in UPDATE_EN  + UPDATE_TA):   return "UPDATE"
    return "ADD"


def extract_items(text: str, menu_names: list) -> list:
    t = _normalise(text)
    t = _translate(t)
    matched = []
    for name in menu_names:   # sorted longest-first by menu_loader
        if name in t:
            matched.append(name)
            t = t.replace(name, ' ', 1)
    return matched


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def parse_command(text: str, menu_names: list):
    """
    Returns (intent, items, qty).
    Works for English, Tamil script, and romanised Tamil input.
    """
    if not text:
        return ("UNKNOWN", [], 1)
    t      = _normalise(text)
    intent = extract_intent(t)
    items  = extract_items(t, menu_names)
    qty    = extract_quantity(t)
    return (intent, items, qty)


def parse_multi_item_command(text: str, menu_names: list) -> list:
    """
    Handles "two idli and three naan" / "rendu idli moonu naan" style.
    Returns list of (item_name, qty) tuples.
    """
    t = _normalise(text)
    t = _translate(t)
    results = []
    for item_name in menu_names:
        if item_name not in t:
            continue
        pattern = r'(?:(\S+)\s+)?' + re.escape(item_name)
        match   = re.search(pattern, t)
        qty     = 1
        if match and match.group(1):
            token = match.group(1).strip()
            if token.isdigit():
                qty = int(token)
            elif token in TAMIL_NUMS:
                qty = TAMIL_NUMS[token]
            elif token in ENGLISH_NUMS:
                qty = ENGLISH_NUMS[token]
        results.append((item_name, qty))
        t = t.replace(item_name, ' ', 1)
    return results
