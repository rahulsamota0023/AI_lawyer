"""Rule-based language detection and problem-type routing (English / Hindi / Hinglish).
Rules first: cheap, deterministic, testable. The LLM is only asked when rules find nothing."""
import re

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_HINGLISH_MARKERS = re.compile(
    r"\b(hai|hain|nahi|nahin|mujhe|mera|meri|mere|kiya|kar|raha|rahi|nhi|ko|ka|ki|ke|se|par|ne|wapas|vapas|paise|paisa|"
    r"malik|makaan|kiraya|tankhwah|salary nahi|de nahi|diya|diye|bola|bol|kya|kaise|aap|tum|abhi|mahine|mahina)\b", re.I)


def detect_lang(text: str) -> str:
    """'hi' (Devanagari), 'hinglish' (Roman-script Hindi) or 'en'."""
    letters = [c for c in text if c.isalpha()]
    if letters:
        dev = sum(1 for c in letters if _DEVANAGARI.match(c))
        if dev / len(letters) > 0.3:
            return "hi"
    if len(_HINGLISH_MARKERS.findall(text)) >= 2:
        return "hinglish"
    return "en"


def devanagari_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return (sum(1 for c in letters if _DEVANAGARI.match(c)) / len(letters)) if letters else 0.0


_RULES = {
    "tenancy": [r"\bdeposit\b", r"security deposit", r"\blandlord\b", r"\blandlady\b", r"\btenant\b", r"\brent(ed|al)?\b",
                r"\bflat\b", r"\bpg\b", r"house owner", r"makaan\s*malik", r"\bkiraya\b", r"\bkirayedar\b",
                r"मकान\s*मालिक", r"किराया", r"किरायेदार", r"डिपॉ?ज़?ि?ट", r"सिक्योरिटी", r"एडवांस"],
    "consumer": [r"\brefund", r"\bdefective\b", r"\bdamaged\b", r"\bwarranty\b", r"\breplace(ment)?\b", r"\bdelivery\b",
                 r"\border(ed)?\b", r"\bamazon\b", r"\bflipkart\b", r"\bswiggy\b", r"\bzomato\b", r"\bcoaching\b",
                 r"\bcourse fee", r"\bairline\b", r"\bseller\b", r"\bshop\b", r"\bbought\b", r"\bpurchase",
                 r"रिफंड", r"खराब", r"वारंटी", r"खरीद", r"दुकान", r"पैसे\s*वापस", r"सामान"],
    "wages": [r"\bsalary\b", r"\bwages?\b", r"\bunpaid\b", r"\bemployer\b", r"\bresign", r"full and final", r"\bf&f\b",
              r"\bfnf\b", r"notice period", r"\bpayslip", r"\btankhwah\b", r"\bsalary nahi",
              r"सैलरी", r"वेतन", r"तनख़?्?वाह", r"तनखा", r"नौकरी", r"कंपनी\s*ने"],
}
_COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in _RULES.items()}


def classify_rules(text: str):
    """Return (category or None, scores). Ties broken by tenancy > wages > consumer (most specific words first)."""
    scores = {k: sum(1 for p in pats if p.search(text)) for k, pats in _COMPILED.items()}
    best = max(scores.values())
    if best == 0:
        return None, scores
    for k in ("tenancy", "wages", "consumer"):
        if scores[k] == best:
            return k, scores
    return None, scores
