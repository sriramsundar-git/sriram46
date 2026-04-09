"""
auto_nlp_updater.py
───────────────────
When a new food item is added via admin, this module:
 1. Generates Tamil script + romanised variants for the item name
 2. Appends them INSIDE TAMIL_FOOD_MAP in nlp_parser.py (brace-counting insert)
 3. Returns a summary of what was added

Word dictionary covers 60+ common food words with Tamil script + Chrome SR romanised variants.
For unknown words it keeps the English form as-is.
"""

import re, os, ast

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
NLP_FILE  = os.path.join(BASE_DIR, "nlp_parser.py")

# ── Word-level Tamil dictionary ───────────────────────────────────────────
WORD_DICT = {
    "chicken"   : ("சிக்கன்",    ["chicken","chiken","cicken"]),
    "paneer"    : ("பனீர்",      ["paneer","panir","panneer"]),
    "mutton"    : ("மட்டன்",     ["mutton","matton"]),
    "fish"      : ("மீன்",       ["meen","fish"]),
    "egg"       : ("முட்டை",     ["muttai","egg","muddai"]),
    "prawn"     : ("இறால்",      ["iral","prawn"]),
    "tofu"      : ("டோஃபு",      ["tofu"]),
    "rice"      : ("சாதம்",      ["sadam","soru","rice"]),
    "naan"      : ("நான்",       ["naan","nan","naai"]),
    "roti"      : ("ரொட்டி",     ["roti","chapati","chapathi"]),
    "parotta"   : ("பரோட்டா",    ["parotta","parota"]),
    "idli"      : ("இட்லி",      ["idli","idly"]),
    "dosa"      : ("தோசை",       ["dosa","dosai","dose"]),
    "biryani"   : ("பிரியாணி",   ["biryani","biriyani","briyani","biriani"]),
    "puri"      : ("பூரி",        ["puri","poori"]),
    "bread"     : ("பிரட்",      ["bread"]),
    "uttapam"   : ("உத்தப்பம்",  ["uttapam","oothappam"]),
    "appam"     : ("ஆப்பம்",     ["appam"]),
    "puttu"     : ("புட்டு",     ["puttu"]),
    "kottu"     : ("கொத்து",     ["kottu"]),
    "masala"    : ("மசாலா",      ["masala","masaala","masalaa"]),
    "curry"     : ("கறி",        ["curry","kari","kozhambu","kulambu"]),
    "dal"       : ("தால்",       ["dal","dhal","paruppu","parupu"]),
    "sambar"    : ("சாம்பார்",   ["sambar","sambhar"]),
    "rasam"     : ("ரசம்",       ["rasam"]),
    "soup"      : ("சூப்",       ["soup","supp","suppuu"]),
    "salad"     : ("சாலட்",      ["salad"]),
    "fry"       : ("வறுவல்",     ["fry","fries"]),
    "fried"     : ("வறுத்த",     ["fried"]),
    "veg"       : ("காய்கறி",    ["veg","veggie"]),
    "butter"    : ("வெண்ணெய்",   ["butter","batter"]),
    "chilli"    : ("மிளகாய்",    ["chilli","chili"]),
    "pepper"    : ("மிளகு",      ["pepper"]),
    "garlic"    : ("பூண்டு",     ["garlic","poondu"]),
    "onion"     : ("வெங்காயம்",  ["onion"]),
    "tomato"    : ("தக்காளி",    ["tomato","thakkali"]),
    "mushroom"  : ("காளான்",     ["mushroom","kaalan"]),
    "corn"      : ("சோளம்",      ["corn"]),
    "palak"     : ("கீரை",       ["palak","keerai"]),
    "samosa"    : ("சமோசா",      ["samosa","samoosa"]),
    "bajji"     : ("பஜ்ஜி",      ["bajji","bhaji"]),
    "bonda"     : ("போண்டா",     ["bonda"]),
    "vadai"     : ("வடை",        ["vadai","vada","wada"]),
    "pakoda"    : ("பகோடா",      ["pakoda","pakora"]),
    "chai"      : ("சாய்",       ["chai","chaai","chay","tea"]),
    "coffee"    : ("காபி",       ["coffee","kaapi","kappi"]),
    "lassi"     : ("லஸ்சி",      ["lassi"]),
    "juice"     : ("ஜூஸ்",       ["juice","joos"]),
    "milk"      : ("பால்",       ["milk","paal"]),
    "water"     : ("தண்ணீர்",    ["water","thanneer"]),
    "soda"      : ("சோடா",       ["soda"]),
    "shake"     : ("ஷேக்",       ["shake","shaek"]),
    "smoothie"  : ("ஸ்மூதி",     ["smoothie"]),
    "mango"     : ("மாம்பழம்",   ["mango","maambalam"]),
    "banana"    : ("வாழைப்பழம்", ["banana","vazhai"]),
    "apple"     : ("ஆப்பிள்",    ["apple"]),
    "guava"     : ("கொய்யா",     ["guava"]),
    "pineapple" : ("அன்னாசி",    ["pineapple","annasi"]),
    "gulab"     : ("குலாப்",     ["gulab"]),
    "jamun"     : ("ஜாமுன்",     ["jamun"]),
    "halwa"     : ("அல்வா",      ["halwa","alva"]),
    "payasam"   : ("பாயாசம்",    ["payasam","kheer"]),
    "kulfi"     : ("குல்ஃபி",    ["kulfi"]),
    "ice"       : ("ஐஸ்",        ["ice","ais"]),
    "cream"     : ("கிரீம்",     ["cream","kireem"]),
    "cake"      : ("கேக்",       ["cake","kaek"]),
    "pudding"   : ("புட்டிங்",   ["pudding"]),
    "grilled"   : ("வறுத்த",     ["grilled","grill"]),
    "roasted"   : ("சுட்ட",      ["roasted","roast"]),
    "steamed"   : ("வேகவைத்த",   ["steamed","steam"]),
    "tandoori"  : ("தந்தூரி",    ["tandoori","tanduri"]),
    "spicy"     : ("காரமான",     ["spicy"]),
    "sweet"     : ("இனிப்பு",    ["sweet","inippu"]),
    "tikka"     : ("tikka",      ["tikka","tika"]),
    "panipuri"  : ("பானிபூரி",   ["panipuri","pani puri"]),
    "lemonade"  : ("எலுமிச்சை",  ["lemonade"]),
}


def _tokenise(name: str) -> list:
    return re.findall(r'[a-zA-Z]+', name.lower())


def generate_variants(item_name: str) -> dict:
    """
    Generate Tamil script + romanised variants for an English item name.
    Returns dict with keys: tamil_script, romanised (list), or None if unknown.
    """
    words         = _tokenise(item_name)
    tamil_parts   = []
    roman_options = [[]]
    known_any     = False

    for word in words:
        entry = WORD_DICT.get(word)
        if entry:
            known_any = True
            script, variants = entry
            tamil_parts.append(script)
            roman_options = [prev + [v] for prev in roman_options for v in variants]
        else:
            tamil_parts.append(word)
            roman_options = [prev + [word] for prev in roman_options]

    if not known_any:
        return None

    tamil_script   = " ".join(tamil_parts).strip()
    romanised_list = sorted({" ".join(parts) for parts in roman_options}, key=len)[:8]

    return {"tamil_script": tamil_script, "romanised": romanised_list}


def _insert_into_food_map(content: str, new_entries: dict, item_name: str) -> str:
    """
    Insert new_entries into TAMIL_FOOD_MAP in nlp_parser.py source.
    Uses brace-counting to find the exact closing } of the dict.
    New entries are inserted just before that closing brace.
    """
    map_start = content.find("TAMIL_FOOD_MAP = {")
    if map_start == -1:
        raise ValueError("TAMIL_FOOD_MAP not found in nlp_parser.py")

    # Count braces to find the matching closing }
    depth     = 0
    close_pos = -1
    for i, ch in enumerate(content[map_start:], map_start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                close_pos = i
                break

    if close_pos == -1:
        raise ValueError("Could not find closing } of TAMIL_FOOD_MAP")

    # Build insertion block
    lines = [f"\n    # ── {item_name.title()} (auto-added) ──────────────────"]
    for k, v in new_entries.items():
        lines.append(f'    "{k}":"{v}",')
    block = "\n".join(lines) + "\n"

    return content[:close_pos] + block + content[close_pos:]


def update_nlp_parser(item_name: str, target_name: str = None) -> dict:
    """
    Add Tamil + English NLP entries for a new menu item.

    item_name   : English name as typed in admin (e.g. "chicken biryani")
    target_name : Menu key to map TO  (defaults to item_name.lower())

    Returns {"added": [list of keys added], "skipped": reason or None}
    """
    if target_name is None:
        target_name = item_name.lower().strip()

    variants = generate_variants(item_name)

    with open(NLP_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Collect entries that don't already exist as KEYS in the dict.
    # We check for the key pattern "entry": rather than just "entry" anywhere,
    # because the string may appear in comments or as a dict value.
    def _is_key(s):
        return bool(re.search(r'"' + re.escape(s) + r'"\s*:', content))

    candidates = {}

    # Always include the exact English name as a key
    exact = item_name.lower().strip()
    if not _is_key(exact):
        candidates[exact] = target_name

    if variants:
        ts = variants["tamil_script"]
        if ts and not _is_key(ts):
            candidates[ts] = target_name
        for rv in variants["romanised"]:
            if rv != exact and not _is_key(rv):
                candidates[rv] = target_name

    if not candidates:
        return {"added": [], "skipped": "All variants already exist."}

    try:
        new_content = _insert_into_food_map(content, candidates, item_name)
        # Validate before writing
        ast.parse(new_content)
        with open(NLP_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)
        return {"added": list(candidates.keys()), "skipped": None}
    except Exception as e:
        return {"added": [], "skipped": f"Error: {e}"}


def auto_register_item(item_name: str) -> dict:
    """
    Main entry point called by app.py after a new item is added.
    Updates nlp_parser.py with Tamil + English voice variants.
    Returns summary dict.
    """
    result = update_nlp_parser(item_name, item_name.lower().strip())
    return {
        "nlp_entries_added": result["added"],
        "skipped"          : result["skipped"],
    }
