"""
Flow definition load + validate.

Validation startup par chalti hai, request par nahi. Ek galat button title
ya dangling next server start hote hi pakda jaayega — user ke saamne nahi.
"""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

FLOW_PATH = Path(__file__).resolve().parents[2] / "flows" / "main.json"

MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_LIST_ROWS = 10
MAX_ROW_TITLE = 24

LANGS = ("hi", "en")


class FlowError(Exception):
    """Flow definition galat hai — startup par hi fail karo."""


def _check_i18n(val, where: str, max_len: int = 0):
    if not isinstance(val, dict):
        raise FlowError(f"{where}: text {{'hi': ..., 'en': ...}} hona chahiye, mila: {val!r}")
    for lang in LANGS:
        if lang not in val:
            raise FlowError(f"{where}: '{lang}' text missing (dono bhasha zaroori hain)")
        if max_len and len(val[lang]) > max_len:
            raise FlowError(
                f"{where}: '{lang}' text {max_len} chars se lamba "
                f"({len(val[lang])}): {val[lang]!r}"
            )


def _validate(flow: dict) -> None:
    screens = flow.get("screens")
    if not screens:
        raise FlowError("flow mein 'screens' nahi hai")

    start = flow.get("start")
    if start not in screens:
        raise FlowError(f"start screen '{start}' exist nahi karta")

    # payload id -> target. Ek id do jagah alag next par jaaye to routing tut jaayega.
    targets: dict = {}
    # id_prefix -> target, dynamic rows (LOC_0, LOC_1, ...) ke liye
    dynamic: dict = {}

    def _register(bid: str, nxt: str, where: str):
        if nxt not in screens:
            raise FlowError(f"{where}: next '{nxt}' naam ka koi screen nahi hai")
        if bid in targets and targets[bid] != nxt:
            raise FlowError(
                f"button id '{bid}' do alag jagah alag screen par jaata hai "
                f"('{targets[bid]}' aur '{nxt}'). Ek id ka ek hi matlab hona chahiye."
            )
        targets[bid] = nxt

    for name, s in screens.items():
        stype = s.get("type")
        if stype not in ("buttons", "list", "text", "input", "action"):
            raise FlowError(f"{name}: type '{stype}' galat hai")

        if stype != "action":
            _check_i18n(s.get("body"), f"{name}.body")

        for key in ("next", "on_error", "on_missing", "input_next", "input_error"):
            if key in s and s[key] not in screens:
                raise FlowError(f"{name}.{key}: '{s[key]}' naam ka koi screen nahi hai")

        if stype == "buttons":
            btns = s.get("buttons") or []
            if not btns:
                raise FlowError(f"{name}: type=buttons hai par koi button nahi")
            if len(btns) > MAX_BUTTONS:
                raise FlowError(
                    f"{name}: {len(btns)} buttons hain, WhatsApp max {MAX_BUTTONS} deta hai. "
                    f"type=list use karein."
                )
            for b in btns:
                _check_i18n(b.get("title"), f"{name}.button[{b.get('id')}].title", MAX_BUTTON_TITLE)
                _register(b["id"], b["next"], f"{name}.button[{b['id']}]")
                if "on_error" in b and b["on_error"] not in screens:
                    raise FlowError(f"{name}.button[{b['id']}].on_error: '{b['on_error']}' screen nahi hai")

        elif stype == "list":
            _check_i18n(s.get("list_button"), f"{name}.list_button", MAX_BUTTON_TITLE)

            # Dynamic list (jaise connected locations) — rows runtime par bante hain
            dyn = s.get("dynamic_rows")
            if dyn:
                for key in ("source", "id_prefix", "next"):
                    if not dyn.get(key):
                        raise FlowError(f"{name}.dynamic_rows: '{key}' missing")
                for key in ("next", "empty"):
                    if dyn.get(key) and dyn[key] not in screens:
                        raise FlowError(f"{name}.dynamic_rows.{key}: '{dyn[key]}' screen nahi hai")
                dynamic[dyn["id_prefix"]] = dyn["next"]
                continue

            rows_total = 0
            for sec in s.get("sections") or []:
                _check_i18n(sec.get("title"), f"{name}.section.title")
                for row in sec.get("rows") or []:
                    rows_total += 1
                    _check_i18n(row.get("title"), f"{name}.row[{row.get('id')}].title", MAX_ROW_TITLE)
                    if "description" in row:
                        _check_i18n(row["description"], f"{name}.row[{row.get('id')}].description")
                    _register(row["id"], row["next"], f"{name}.row[{row['id']}]")
            if rows_total == 0:
                raise FlowError(f"{name}: type=list hai par koi row nahi")
            if rows_total > MAX_LIST_ROWS:
                raise FlowError(
                    f"{name}: {rows_total} rows hain, WhatsApp max {MAX_LIST_ROWS} deta hai"
                )

        elif stype in ("input", "action"):
            if not s.get("action"):
                raise FlowError(f"{name}: type={stype} hai par 'action' nahi diya")
            if not s.get("next"):
                raise FlowError(f"{name}: type={stype} hai par 'next' nahi diya")

    for key, val in (flow.get("texts") or {}).items():
        if key.startswith("_"):
            continue
        _check_i18n(val, f"texts.{key}")

    # Feature chain: map (button -> feature), chain (feature -> agla screen), labels
    feats = flow.get("features") or {}
    fmap = feats.get("map") or {}
    for btn, feat in fmap.items():
        if btn in targets and btn not in (b for b in fmap):
            pass  # button ka apna next bhi ho sakta hai, koi dikkat nahi
    for feat, scr in (feats.get("chain") or {}).items():
        if scr not in screens:
            raise FlowError(f"features.chain['{feat}']: '{scr}' naam ka screen nahi hai")
    for feat, lab in (feats.get("labels") or {}).items():
        _check_i18n(lab, f"features.labels.{feat}")

    flow["_targets"] = targets
    flow["_dynamic"] = dynamic
    log.info("Flow OK — %d screens, %d button ids, %d texts, %d features",
             len(screens), len(targets), len(flow.get("texts") or {}),
             len(fmap))


def load_flow(path: Path = FLOW_PATH) -> dict:
    if not path.exists():
        raise FlowError(f"Flow file nahi mili: {path}")
    with open(path, encoding="utf-8") as f:
        flow = json.load(f)
    _validate(flow)
    return flow


FLOW = load_flow()


def screen(name: str) -> dict:
    s = FLOW["screens"].get(name)
    if s is None:
        raise FlowError(f"screen '{name}' exist nahi karta")
    return s


def text(key: str) -> dict:
    """texts.* se i18n dict. Missing key startup par nahi, yahin pakda jaayega."""
    t = (FLOW.get("texts") or {}).get(key)
    if t is None:
        raise FlowError(f"texts.{key} flow mein nahi hai")
    return t


import re as _re

# Typed text ko button se match karne ke liye — yes/no/haan/nahi + aam synonyms
_AFFIRM = {
    "yes", "yeah", "yea", "yep", "yup", "ya", "sure", "ok", "okay", "k", "yess",
    "haan", "han", "ha", "hn", "haa", "ji", "jee", "jaruri", "zaroor", "theek",
    "thik", "sahi", "chalega", "done", "ready", "start", "karo", "karenge",
    "chahiye", "interested", "intrested", "yesss", "haanji",
}
_NEGATIVE = {
    "no", "nope", "nah", "naa", "na", "nahi", "nhi", "nahin", "cancel",
    "later", "baad", "skip", "mat", "nope.",
}


def _norm(s: str) -> str:
    """Emoji/punctuation hata, lowercase, spaces collapse."""
    s = _re.sub(r"[^\w\s]", " ", str(s), flags=_re.UNICODE)
    return _re.sub(r"\s+", " ", s).strip().lower()


def match_typed_button(screen_name: str, text: str) -> str:
    """
    User ne button ka jawab TYPE kiya (click nahi) — usse button id nikaalo.

    'Yes'/'haan'/'yeah' -> affirmative button, 'No'/'nahi' -> negative button,
    ya seedha button ke title se match ('plans', 'connect', etc.).

    Yeh hybrid ka dil hai: click ya type, dono ek jaisa kaam karein.
    """
    t = _norm(text)
    if not t:
        return ""

    s = FLOW["screens"].get(screen_name) or {}
    btns = list(s.get("buttons", []))
    for sec in s.get("sections", []):
        btns.extend(sec.get("rows", []))
    if not btns:
        return ""

    norm_titles = []  # (button, set-of-normalized-titles)
    for b in btns:
        titles = {_norm(b["title"].get(l, "")) for l in LANGS}
        titles.discard("")
        norm_titles.append((b, titles))

    # 1. Seedha title match (exact ya andar)
    for b, titles in norm_titles:
        if t in titles:
            return b["id"]
    for b, titles in norm_titles:
        for tt in titles:
            if tt and (t == tt or (len(t) >= 3 and (t in tt or tt in t))):
                return b["id"]

    # 2. Yes/No synonyms -> affirmative/negative button.
    # SIRF chhote jawab par (<= 3 shabd). "Nahi yrr kuch bhi de diya tune" jaisi
    # lambi frustration ko "nahi"=No mat samjho — woh AI ke paas jaani chahiye.
    tokens = t.split()
    if len(tokens) > 3:
        return ""
    words = set(tokens)
    is_yes = bool(words & _AFFIRM) or t in _AFFIRM
    is_no = bool(words & _NEGATIVE) or t in _NEGATIVE

    # Typo-tolerant: "yeaah", "yesss", "haaan", "okk" jaise variants bhi pakdo
    if not is_yes and not is_no:
        if _re.match(r"^(y+e+a*h*|ya+|ha+n?|o+k+|s+u+r+e+|ji+)$", t.replace(" ", "")):
            is_yes = True
        elif _re.match(r"^(n+o+|n+a+h*i*n*|na+)$", t.replace(" ", "")):
            is_no = True
    if is_yes and not is_no:
        for b, titles in norm_titles:
            if any(w in tt for tt in titles for w in ("yes", "haan", "ha")):
                return b["id"]
    if is_no and not is_yes:
        # Pehle asli "No"/"Later" button dhoondo
        for b, titles in norm_titles:
            if any(w in tt for tt in titles for w in ("no", "nahi", "later", "baad")):
                return b["id"]
        # Warna "nahi/ye nahi" ka matlab "yeh nahi, doosra dikhao" — jaise
        # CONFIRM_BUSINESS par "Show another"/"Doosra dikhao"
        for b, titles in norm_titles:
            if any(w in tt for tt in titles for w in ("doosra", "dusra", "another", "next", "agla")):
                return b["id"]

    return ""


def button_by_title(screen_name: str, title: str) -> str:
    """
    Title se button id nikaalo — ek screen ke andar.

    ZAROORI: yeh platform ne interactive buttons ka id wapas bhejna band kiya
    isliye chahiye. Tap par sirf title (jaise '✅ Yes') aata hai, id nahi.
    Current screen ke buttons/rows ke title (dono bhasha) se match karke id
    wapas laate hain — screen ke andar title unique hota hai, isliye saaf.
    """
    title = (title or "").strip()
    if not title:
        return ""
    s = FLOW["screens"].get(screen_name) or {}

    for b in s.get("buttons", []):
        for lang in LANGS:
            if (b["title"].get(lang) or "").strip() == title:
                return b["id"]

    for sec in s.get("sections", []):
        for row in sec.get("rows", []):
            for lang in LANGS:
                if (row["title"].get(lang) or "").strip() == title:
                    return row["id"]

    return ""


def target_for(button_id: str) -> str:
    """Kisi bhi screen ka button id -> target screen. Na mile to ''."""
    hit = FLOW["_targets"].get(button_id)
    if hit:
        return hit
    # Dynamic rows: LOC_0, LOC_1, ... -> prefix se match
    for prefix, nxt in FLOW["_dynamic"].items():
        if button_id.startswith(prefix):
            return nxt
    return ""


def start_screen() -> str:
    return FLOW["start"]


def features() -> dict:
    """Feature chain config: {map, chain, labels}."""
    return FLOW.get("features") or {}


def media_ready(media: dict) -> bool:
    """<<<placeholder>>> URL abhi bhejne layak nahi hain."""
    url = (media or {}).get("url", "")
    return bool(url) and not url.startswith("<<<")
