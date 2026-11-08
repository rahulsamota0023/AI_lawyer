"""Code-level guardrails. Nothing here calls an LLM.

1. check_reply():  strips any legal citation that is not in the knowledge base (sections of unknown acts,
                   case law, repealed acts presented as current, invented interest rates).
2. pre_check():    escalation rules that run BEFORE the model (self-harm, violence, out-of-scope, etc.).
3. post_flags():   soft escalations computed from the case card (big amounts, limitation clock).
"""
import re
from . import kb

REMOVED_MARK_EN = "[A legal citation here could not be verified, so it was removed. Please ask a lawyer to confirm.]"
REMOVED_MARK_HI = "[यहाँ दिया गया एक कानूनी हवाला सत्यापित नहीं हो सका, इसलिए हटा दिया गया। कृपया वकील से पुष्टि करें।]"

# ---------------------------------------------------------------- citation checker
_PROTECT = re.compile(r"\b(Sec|Secs|Rs|No|Nos|Art|Arts|vs|v|Dr|Mr|Mrs|Ms|Ss|s|approx|etc|Ltd|Pvt)\.", re.I)
_SPLIT = re.compile(r"[^.!?।\n]+(?:[.!?।]+|\n+|$)\s*")

_REF = re.compile(
    r"(?i)(?P<kind>\bsections?\b|\bsecs?\b\.?|\bss?\.(?=\s*\d)|\bu/s\b|धारा|\barticles?\b|\barts?\b\.?|\border\b|\brules?\b)"
    r"\s*(?P<num>\d+[A-Za-z]?(?:\s*\(\s*\w+\s*\))*)")
_CASE_V = re.compile(r"\b[A-Z][A-Za-z.&']+(?:\s+[A-Za-z.&']+){0,4}\s+(?:v\.|vs\.?|v/s|versus)\s+[A-Z][A-Za-z.&']+")
_CASE_REPORTER = re.compile(r"(?i)\bAIR\s*(?:19|20)\d{2}\b|\bSCC\b|\bSCR\b|\bCPJ\b|\bCTJ\b|\(\d{4}\)\s*\d+\s*(?:SCC|CPJ)|\bMANU/|\bJT\s*\d{4}")
_COURT_HELD = re.compile(r"(?i)\b(?:supreme court|high court|ncdrc|national commission|state commission|district commission|tribunal)\b[^.!?]{0,40}\b(?:has\s+)?(?:held|ruled|observed|decided|laid down)\b")
_CASE_WORDS = re.compile(r"(?i)\bin the case of\b|\bas held in\b|\bthe judgment in\b|\bprecedent set by\b")
_INTEREST = re.compile(r"(?i)\b\d{1,2}(?:\.\d+)?\s?%\s*(?:per\s*annum|p\.?\s?a\.?|interest|annual|सालाना)|interest\s+(?:at|of)\s+(?:the\s+rate\s+of\s+)?\d{1,2}(?:\.\d+)?\s?%")
_ACT_NUM = re.compile(r"(?i)\b(?:ipc|bns|bnss|crpc|cpc|ni act|n\.i\. act)\s*[-:]?\s*(?:s\.?\s*)?\d+|\b\d+\s*(?:of\s+)?(?:ipc|bns|bnss|crpc|ni act)\b")
_COURTS_RULED = re.compile(r"(?i)\b(?:courts?|judges?)\b[^.!?]{0,40}\b(?:have|has)?\s*(?:consistently\s+|repeatedly\s+)?(?:held|ruled|decided|observed)\b")
_HEDGE = re.compile(r"(?i)\bmay\b|\bmight\b|\bcould\b|lawyer|वकील|सकता")
_NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
_QTY = re.compile(r"(?i)\b(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s*-?\s*(years?|months?|working days|days?|lakhs?|lacs?|crores?|times|%|percent|per\s*cent)")
_REPEAL_CONTEXT = re.compile(r"(?i)repeal|replaced|replaces|subsum|earlier|old law|previously|no longer|superseded|निरस्त|बदल|पुराना|पहले|हट")


def _canon_unit(u):
    u = re.sub(r"\s+", "", u.lower())
    if u in ("%", "percent"):
        return "%"
    if u in ("times", "workingdays"):
        return u
    if u.startswith(("lakh", "lac")):
        return "lakh"
    if u.startswith("crore"):
        return "crore"
    return re.sub(r"s$", "", u)


def _qty_tokens(text):
    """{'2 year', '50 lakh', ...}: number words -> digits, units canonical."""
    out = set()
    for m in _QTY.finditer(text):
        n = m.group(1).lower()
        n = str(_NUMWORDS[n]) if n in _NUMWORDS else re.sub(r"\.0$", "", n)
        out.add(f"{n} {_canon_unit(m.group(2))}")
    return out


def _kb_quantities():
    """({act_key: tokens}, global tokens from procedure steps). Built from the verified KB text only."""
    per_act, glob = {}, set()
    for t in kb.topics().values():
        for p in t["provisions"]:
            per_act.setdefault(p["act_key"], set()).update(_qty_tokens(p["plain"] + " " + p["cite_as"]))
        glob |= _qty_tokens(" ".join(t["procedure"]["steps"]))
    return per_act, glob


def _alias_index():
    """[(alias, act_key)] sorted longest first so 'consumer protection act, 1986' beats 'consumer protection act'."""
    pairs = []
    for key, a in kb.acts().items():
        for al in a["aliases"]:
            pairs.append((al.lower(), key))
    pairs.sort(key=lambda x: -len(x[0]))
    return pairs


def _acts_in(sentence):
    """[(pos, end, act_key)] non-overlapping, longest alias wins."""
    s = sentence.lower()
    taken, found = [], []
    for alias, key in _alias_index():
        for m in re.finditer(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", s):
            if any(not (m.end() <= a or m.start() >= b) for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            found.append((m.start(), m.end(), key))
    return sorted(found)


def _norm(num):
    return re.sub(r"\s+", "", num).lower()


def _section_ok(act_key, num, allowed):
    secs = allowed.get(act_key)
    if secs is None:
        return False
    n = _norm(num)
    return n in secs or any(n.startswith(s + "(") for s in secs if "(" not in s)


def _check_sentence(sent, last_act, allowed, user_qty=frozenset()):
    """Return (reason, detail) if the sentence must be removed, else None. Also returns act to carry forward."""
    acts = _acts_in(sent)
    # repealed act presented as current law
    for _, _, key in acts:
        a = kb.acts()[key]
        if a["status"] == "repealed" and not _REPEAL_CONTEXT.search(sent):
            return ("repealed_act", f"{a['name']} is repealed ({a.get('repealed_by', '')})")
    if _CASE_REPORTER.search(sent) or _CASE_V.search(sent) or _COURT_HELD.search(sent) or _CASE_WORDS.search(sent) or _COURTS_RULED.search(sent):
        return ("case_law", "court cases are never cited (cannot be verified)")
    if _INTEREST.search(sent):
        return ("interest_rate", "specific interest rate stated as law")
    if _ACT_NUM.search(sent):
        return ("unverified_section", "criminal/other-code section number outside the knowledge base")
    for _, _, key in acts:  # relying on an act we hold no verified text for
        if kb.acts()[key]["status"] == "not_covered" and not _HEDGE.search(sent):
            return ("act_not_in_kb", f"{kb.acts()[key]['name']} is not covered by the verified knowledge base")
    for m in _REF.finditer(sent):
        kind = m.group("kind").lower()
        num = m.group("num")
        # find the act this reference belongs to: nearest act mention after it, else before it, else carried forward
        after = [a for a in acts if a[0] >= m.end()]
        before = [a for a in acts if a[1] <= m.start()]
        act = after[0][2] if after else before[-1][2] if before else last_act
        if act is None:
            return ("no_act", f"'{m.group(0)}' cited without naming an act")
        if kind.startswith(("article", "art", "order")):
            return ("unverified_section", f"{m.group(0)} ({act})")
        if not _section_ok(act, num, allowed):
            return ("unverified_section", f"{m.group(0)} of {kb.acts()[act]['name']} is not in the knowledge base")
    # right citation, wrong content: any 'N years/months/days/lakh/times/%' in a sentence that names an act must appear
    # in that act's verified text, in the procedure steps, or in what the user themselves said
    cited = {k for _, _, k in acts if k in kb.allowed_sections()} | ({last_act} if _REF.search(sent) and last_act and not acts else set())
    if cited:
        per_act, glob = _kb_quantities()
        ok = set(glob) | set(user_qty)
        for k in cited:
            ok |= per_act.get(k, set())
        bad = _qty_tokens(sent) - ok
        if bad:
            return ("unverified_figure", f"figure(s) {sorted(bad)} not found in the verified text of {sorted(cited)}")
    return None


def check_reply(text: str, lang: str = "en", user_text: str = ""):
    """Return (clean_text, report). Unverified citations are removed sentence-by-sentence.
    user_text: what the user said; figures they stated themselves (e.g. '3 months unpaid') are not flagged."""
    allowed = kb.allowed_sections()
    user_qty = _qty_tokens(user_text)
    protected = _PROTECT.sub(lambda m: m.group(1) + "\u2024", text)
    parts = _SPLIT.findall(protected) or [protected]
    out, report, last_act, marked = [], [], None, False
    for part in parts:
        original = part.replace("\u2024", ".")
        verdict = _check_sentence(original, last_act, allowed, user_qty)
        if verdict:
            report.append({"type": verdict[0], "detail": verdict[1], "removed_text": original.strip()})
            if not marked:
                mark = REMOVED_MARK_HI if lang == "hi" else REMOVED_MARK_EN
                out.append(mark + " ")
                marked = True
            continue
        acts = _acts_in(original)
        if acts:
            last_act = acts[-1][2]
        out.append(original)
    clean = "".join(out)
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    return clean.strip(), report


# ---------------------------------------------------------------- escalation rules
_P = lambda *ps: re.compile("|".join(ps), re.I)
SELF_HARM = _P(r"\bsuicide\b", r"kill myself", r"end my life", r"\bwant to die\b", r"खुदकुशी", r"आत्महत्या",
               r"मर\s*जाना\s*चाह", r"जान\s*दे\s*दू", r"mar\s*jaana\s*chahta", r"jaan\s*de\s*dunga")
VIOLENCE = _P(r"threaten(ed|ing)? (to )?(beat|kill|hit|harm)", r"\bbeat me\b", r"\bhit me\b", r"\bkill me\b", r"\bassault",
              r"\bmolest", r"\brape\b", r"\bacid\b", r"\bgoons?\b", r"\bviolen", r"\bdhamki\b", r"जान\s*से\s*मार",
              r"मारने\s*की\s*धमकी", r"मारपीट", r"गुंडे", r"धमकी", r"\bbeat(ing)? (me|us)\b")
OUT_OF_SCOPE = _P(r"\barrest(ed)?\b", r"\bFIR\b", r"police case", r"\bbail\b", r"\bjail\b", r"\bdivorce\b", r"\bcustody\b",
                  r"\bdowry\b", r"498\s?-?a", r"domestic violence", r"last will", r"\binheritance\b", r"\bpartition\b",
                  r"property dispute", r"land dispute", r"\bmutation\b", r"\bevict(ed|ion)?\b", r"cheque bounce",
                  r"dishono[u]?r", r"section 138", r"\bdefamation\b", r"cyber ?crime", r"\bupi fraud\b", r"online fraud",
                  r"income tax notice", r"\bGST\b", r"\btrademark\b", r"\bvisa\b", r"\bimmigration\b",
                  r"accident claim", r"medical negligence", r"गिरफ़?्?तार", r"एफ\s?आई\s?आर", r"जमानत", r"तलाक", r"दहेज",
                  r"वसीयत", r"विरासत", r"बंटवारा", r"जमीन\s*का\s*विवाद", r"बेदखल", r"चेक\s*बाउंस")
RECEIVED_NOTICE = _P(r"(received|got|have|has been served|served with)\s+(a\s+)?(legal\s+)?(notice|summons)",
                     r"(notice|summons)\s+(came|has come|arrived)", r"(नोटिस|समन)\s*(मिला|आया|आई|मिली)",
                     r"(notice|summons)\s+(mila|aaya|aayi)", r"court\s+notice")
CASE_LAW_ASK = _P(r"case\s*law", r"\bjudg(e)?ments?\b", r"\bprecedents?\b", r"supreme court (case|order|said)",
                  r"cite .{0,20}case", r"कोई\s*केस", r"फैसला", r"नज़ीर")
COMMERCIAL = _P(r"for my business", r"\bresale\b", r"commercial purpose", r"\bmy shop\b", r"\bmy company bought",
                r"अपने\s*व्यापार", r"दुकान\s*के\s*लिए")
STATUS_DOUBT = _P(r"\bfreelanc", r"\bcontractor\b", r"\bintern(ship)?\b", r"\bgig\b", r"\bconsultant\b", r"\bnot on payroll\b",
                  r"फ्रीलांस", r"इंटर्न", r"ठेकेदार")

MSG = {
    "self_harm": {
        "en": "I'm really sorry you're going through this. Your safety matters more than any legal problem. Please reach out to someone you trust right now. You can call Tele-MANAS on 14416, and if you are in immediate danger call 112. The money or legal issue can be handled later, and I'm here to help with it whenever you feel ready.",
        "hi": "आप जिस दौर से गुज़र रहे हैं, उसके लिए मुझे सचमुच दुख है। आपकी सुरक्षा किसी भी कानूनी समस्या से ज़्यादा ज़रूरी है। कृपया अभी किसी भरोसेमंद व्यक्ति से बात करें। आप Tele-MANAS (14416) पर कॉल कर सकते हैं, और अगर आप तुरंत खतरे में हैं तो 112 पर कॉल करें। पैसों या कानून का मामला बाद में सुलझाया जा सकता है, और जब आप तैयार हों, मैं मदद के लिए यहाँ हूँ।"},
    "violence": {
        "en": "What you describe (threats or violence) is a safety matter, bigger than a money dispute. If you are in danger right now, call 112. Women can also call 181. For a lawyer's help, you may be eligible for free legal aid: call NALSA on 15100. Please don't handle this alone. Once you are safe, I can still help with the paperwork for the money part.",
        "hi": "आप जो बता रहे हैं (धमकी या हिंसा) वह सुरक्षा का मामला है, सिर्फ़ पैसों का विवाद नहीं। अगर आप अभी खतरे में हैं तो 112 पर कॉल करें। महिलाएँ 181 पर भी कॉल कर सकती हैं। वकील की मदद के लिए आप मुफ़्त कानूनी सहायता के पात्र हो सकते हैं: NALSA 15100 पर कॉल करें। कृपया इसे अकेले न संभालें। सुरक्षित होने के बाद पैसों वाले हिस्से के कागज़ात में मैं मदद कर सकता/सकती हूँ।"},
    "out_of_scope": {
        "en": "This looks like a matter I'm not built to handle (police or criminal cases, family, property, eviction, cheque bounce, tax and similar). A mistake here can be costly, so please speak to a lawyer. You may be eligible for free legal aid through your District Legal Services Authority: call NALSA on 15100. I can help with three things: a rental deposit not returned, a refund or defective product/service, and unpaid salary.",
        "hi": "यह ऐसा मामला लगता है जिसे संभालने के लिए मैं नहीं बना हूँ (पुलिस/आपराधिक मामले, पारिवारिक, संपत्ति, बेदखली, चेक बाउंस, टैक्स आदि)। यहाँ गलती महंगी पड़ सकती है, इसलिए कृपया वकील से बात करें। आप अपने ज़िला विधिक सेवा प्राधिकरण से मुफ़्त कानूनी सहायता के पात्र हो सकते हैं: NALSA 15100 पर कॉल करें। मैं तीन चीज़ों में मदद कर सकता/सकती हूँ: किराये की सिक्योरिटी डिपॉज़िट वापस न मिलना, रिफंड या खराब सामान/सेवा, और बकाया सैलरी।"},
    "unknown_clarify": {
        "en": "I can help with three kinds of problems: (1) a rental security deposit that was not returned, (2) a refund or a defective product/service, (3) unpaid salary. Which one is closest to your problem? A line or two about what happened is enough.",
        "hi": "मैं तीन तरह की समस्याओं में मदद कर सकता/सकती हूँ: (1) किराये की सिक्योरिटी डिपॉज़िट वापस न मिलना, (2) रिफंड या खराब सामान/सेवा, (3) बकाया सैलरी। आपकी समस्या इनमें से किसके सबसे करीब है? क्या हुआ, यह एक-दो पंक्तियों में बता दीजिए।"},
    "amount_high": {
        "en": "The amount is large (over Rs 5 lakh), so a mistake can be expensive. Please have a lawyer review any notice or complaint before you send it.",
        "hi": "रकम बड़ी है (5 लाख रुपये से ज़्यादा), इसलिए गलती महंगी पड़ सकती है। कोई भी नोटिस या शिकायत भेजने से पहले कृपया किसी वकील से जँचवा लें।"},
    "amount_beyond_district": {
        "en": "For consumer complaints, the District Commission hears claims up to Rs 50 lakh. A claim this large may need a different forum and a lawyer.",
        "hi": "उपभोक्ता शिकायतों में ज़िला आयोग 50 लाख रुपये तक के दावे सुनता है। इतने बड़े दावे के लिए अलग फ़ोरम और वकील की ज़रूरत पड़ सकती है।"},
    "limitation_near": {
        "en": "Time is short. Based on the dates you gave, the time limit may end around {deadline} (about {days} days left). Please act soon and consider speaking to a lawyer or legal aid (NALSA 15100).",
        "hi": "समय कम है। आपकी बताई तारीखों के हिसाब से समय-सीमा लगभग {deadline} को खत्म हो सकती है (करीब {days} दिन बचे)। कृपया जल्दी कदम उठाएँ और वकील या कानूनी सहायता (NALSA 15100) से बात करें।"},
    "limitation_expired": {
        "en": "Based on the dates you gave, the usual time limit seems to have passed around {deadline}. In some cases a late claim can still be heard if you explain the delay, but please speak to a lawyer or legal aid (NALSA 15100) before doing anything.",
        "hi": "आपकी बताई तारीखों के हिसाब से सामान्य समय-सीमा लगभग {deadline} को निकल चुकी लगती है। कुछ मामलों में देरी का कारण बताने पर देर से किया गया दावा भी सुना जा सकता है, पर कुछ भी करने से पहले कृपया वकील या कानूनी सहायता (NALSA 15100) से बात करें।"},
    "received_notice": {
        "en": "You mention receiving a notice or summons. These usually carry a reply deadline, and missing it can hurt you. Please show it to a lawyer quickly (or call legal aid on 15100). I can explain general ideas, but I won't draft a reply to it.",
        "hi": "आपने बताया कि आपको नोटिस या समन मिला है। इनमें आमतौर पर जवाब की समय-सीमा होती है, और चूकने पर नुकसान हो सकता है। कृपया इसे जल्दी किसी वकील को दिखाएँ (या कानूनी सहायता 15100 पर कॉल करें)। मैं सामान्य जानकारी दे सकता/सकती हूँ, पर उसका जवाब ड्राफ़्ट नहीं करूँगा/करूँगी।"},
    "case_law": {
        "en": "I don't quote court cases, because I can't verify them and AI tools often invent them. A lawyer or a legal aid clinic can find case law that fits your facts.",
        "hi": "मैं अदालती मामलों के हवाले नहीं देता/देती, क्योंकि मैं उन्हें सत्यापित नहीं कर सकता/सकती और AI अक्सर ऐसे हवाले गढ़ देते हैं। आपके तथ्यों पर लागू फ़ैसले वकील या कानूनी सहायता केंद्र खोज सकते हैं।"},
    "commercial": {
        "en": "If you bought this for business or resale, you may not count as a 'consumer' under Section 2(7) of the Consumer Protection Act, 2019. A lawyer should check this.",
        "hi": "अगर आपने यह व्यापार या पुनर्विक्रय के लिए खरीदा है, तो आप उपभोक्ता संरक्षण अधिनियम, 2019 की धारा 2(7) के तहत 'उपभोक्ता' न माने जाएँ। इसे वकील से जँचवाएँ।"},
    "status_doubt": {
        "en": "Your rights can depend on whether you count as an 'employee' (rather than a contractor, freelancer or intern). Please check this with a lawyer or the state labour office.",
        "hi": "आपके अधिकार इस पर निर्भर कर सकते हैं कि आप 'कर्मचारी' माने जाते हैं या नहीं (ठेकेदार, फ्रीलांसर या इंटर्न नहीं)। कृपया वकील या राज्य के श्रम कार्यालय से इसकी जाँच करा लें।"},
    "pre_nov_2025": {
        "en": "Your wages seem to have fallen due before the Code on Wages came into force (21 Nov 2025). Which law applies to older wages can be tricky, so please confirm with a lawyer or the labour office.",
        "hi": "लगता है आपकी सैलरी वेतन संहिता लागू होने (21 नवंबर 2025) से पहले बकाया हुई। पुराने वेतन पर कौन-सा कानून लागू होगा यह पेचीदा हो सकता है, कृपया वकील या श्रम कार्यालय से पुष्टि करें।"},
}


def _lang_key(lang):
    return "hi" if lang == "hi" else "en"


def message(code, lang="en", **fmt):
    return MSG[code][_lang_key(lang)].format(**fmt) if fmt else MSG[code][_lang_key(lang)]


def pre_check(text: str, category=None):
    """Rules that run on the user's message BEFORE any LLM call.
    Returns list of {code, level('hard'|'soft')}. Hard = stop and show fixed message only."""
    flags = []
    if SELF_HARM.search(text):
        flags.append({"code": "self_harm", "level": "hard"})
        return flags
    if VIOLENCE.search(text):
        flags.append({"code": "violence", "level": "hard"})
        return flags
    if OUT_OF_SCOPE.search(text):
        # hard only when we have no in-scope problem to work with; otherwise the user still gets help with that part
        flags.append({"code": "out_of_scope", "level": "soft" if category else "hard"})
    if RECEIVED_NOTICE.search(text):
        flags.append({"code": "received_notice", "level": "soft"})
    if CASE_LAW_ASK.search(text):
        flags.append({"code": "case_law", "level": "soft"})
    if category == "consumer" and COMMERCIAL.search(text):
        flags.append({"code": "commercial", "level": "soft"})
    if category == "wages" and STATUS_DOUBT.search(text):
        flags.append({"code": "status_doubt", "level": "soft"})
    return flags


def post_flags(case, limitation):
    """Soft escalations from structured data (computed in code, not by the model)."""
    flags = []
    amt = case.get("amount") or 0
    if amt >= 500_000:
        flags.append({"code": "amount_high", "level": "soft"})
    if case.get("category") == "consumer" and amt > 5_000_000:
        flags.append({"code": "amount_beyond_district", "level": "soft"})
    if limitation.get("level") == "near":
        flags.append({"code": "limitation_near", "level": "soft", "fmt": {"deadline": limitation["deadline"], "days": limitation["days_left"]}})
    if limitation.get("level") == "expired":
        flags.append({"code": "limitation_expired", "level": "soft", "fmt": {"deadline": limitation["deadline"]}})
    if case.get("category") == "wages" and case.get("event_date") and case["event_date"] < "2025-11-21":
        flags.append({"code": "pre_nov_2025", "level": "soft"})
    return flags
