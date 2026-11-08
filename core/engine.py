"""Conversation engine. Order of operations per turn:
   rules (language, routing, escalation) -> LLM extracts facts -> code validates + computes -> LLM explains from KB ->
   code-level citation check -> app-added flags/disclaimer.  Rules and checks are code; the model only reads and explains."""
import json
from dataclasses import dataclass, field
from datetime import date

from . import case as C
from . import guardrails as G
from . import kb, prompts, router
from .llm import LLM, LLMError, strip_json


@dataclass
class Session:
    case: dict = field(default_factory=C.empty_case)
    history: list = field(default_factory=list)      # [{'role','content'}]
    practice: list = field(default_factory=list)     # role-play transcript
    practice_on: bool = False
    lang: str = "en"
    turns: int = 0
    today: date = field(default_factory=date.today)


@dataclass
class Result:
    reply: str
    category: str = None
    lang: str = "en"
    flags: list = field(default_factory=list)        # [{'code','level','text'}]
    removed_citations: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    limitation: dict = field(default_factory=dict)
    ready_to_draft: bool = False
    stopped_by_rule: bool = False
    llm_calls: int = 0
    error: str = None

    def full_text(self):
        parts = [self.reply] + [f["text"] for f in self.flags if f.get("text")]
        return "\n\n".join(p for p in parts if p)


def _case_json(case):
    return json.dumps({k: v for k, v in case.items() if v not in (None, [], "")}, ensure_ascii=False, indent=1)


def _flag_texts(raw, lang):
    out = []
    for f in raw:
        out.append({**f, "text": G.message(f["code"], lang, **f.get("fmt", {}))})
    return out


def process_turn(s: Session, user_text: str, llm: LLM) -> Result:
    calls0 = llm.calls
    s.turns += 1
    lang = router.detect_lang(user_text)
    if lang != "en" or len(user_text.split()) >= 4:  # a short English word shouldn't flip a Hindi chat back to English
        s.lang = lang
    user_text = user_text.strip()
    s.history.append({"role": "user", "content": user_text})

    # 1. routing by rules
    if not s.case["category"]:
        cat, _ = router.classify_rules(user_text)
        if cat:
            s.case["category"] = cat

    # 2. escalation rules BEFORE any model call
    pre = G.pre_check(user_text, s.case["category"])
    hard = [f for f in pre if f["level"] == "hard"]
    if hard:
        txt = G.message(hard[0]["code"], s.lang)
        s.history.append({"role": "assistant", "content": txt})
        return Result(reply=txt, category=s.case["category"], lang=s.lang, flags=[{**hard[0], "text": ""}],
                      stopped_by_rule=True, llm_calls=llm.calls - calls0)

    try:
        # 3. LLM fallback classification if rules found nothing
        if not s.case["category"]:
            data = strip_json(llm.chat(prompts.CLASSIFY, [{"role": "user", "content": user_text}], json_mode=True, max_tokens=60)) or {}
            if data.get("category") in kb.topics():
                s.case["category"] = data["category"]
        if not s.case["category"]:
            sys = prompts.CLARIFY
            reply = llm.chat(sys, s.history[-6:], max_tokens=250)
            clean, rep = G.check_reply(reply, s.lang)
            if llm.is_mock:
                clean += "\n\n" + G.message("unknown_clarify", s.lang)
            s.history.append({"role": "assistant", "content": clean})
            return Result(reply=clean, lang=s.lang, removed_citations=rep, llm_calls=llm.calls - calls0)

        # 4. extract facts -> validate -> merge
        ext_user = f"Today's date: {s.today.isoformat()}\nKnown so far: {_case_json(s.case)}\n\nUser message:\n{user_text}"
        updates = strip_json(llm.chat(prompts.extract_system(s.case["category"]), [{"role": "user", "content": ext_user}],
                                      json_mode=True, temperature=0, max_tokens=500))
        C.merge_updates(s.case, {k: v for k, v in (updates or {}).items() if k != "category"})

        # 5. deterministic checks
        lim = C.limitation_status(s.case, s.today)
        missing = C.missing_labels(s.case)
        flags = pre + G.post_flags(s.case, lim)

        # 6. LLM explains, grounded in the KB only
        sys = prompts.reply_system(_case_json(s.case), s.case["category"], missing, flags, s.lang)
        raw = llm.chat(sys, s.history[-10:], max_tokens=700)

        # 7. code-level citation check
        clean, report = G.check_reply(raw, s.lang, " ".join(m['content'] for m in s.history if m['role'] == 'user'))
        s.history.append({"role": "assistant", "content": clean})
        return Result(reply=clean, category=s.case["category"], lang=s.lang, flags=_flag_texts(flags, s.lang),
                      removed_citations=report, missing=[m[0] for m in missing], limitation=lim,
                      ready_to_draft=C.ready_to_draft(s.case), llm_calls=llm.calls - calls0)
    except LLMError as e:
        msg = f"Sorry, the AI model could not answer right now ({e}). Your earlier details are saved. Please try again in a minute."
        return Result(reply=msg, category=s.case["category"], lang=s.lang, error=str(e), llm_calls=llm.calls - calls0)


# ------------------------------------------------------------------ practice mode
def practice_turn(s: Session, user_text: str, llm: LLM) -> Result:
    if not s.case["category"]:
        return Result(reply="Tell me about your problem first, then we can practise.", lang=s.lang)
    calls0 = llm.calls
    s.practice.append({"role": "user", "content": user_text})
    try:
        raw = llm.chat(prompts.roleplay_system(_case_json(s.case), s.case["category"], s.lang), s.practice[-10:], max_tokens=300)
    except LLMError as e:
        s.practice.pop()
        return Result(reply=f"Model error: {e}", error=str(e), lang=s.lang)
    clean, rep = G.check_reply(raw, s.lang)
    s.practice.append({"role": "assistant", "content": clean})
    return Result(reply=clean, category=s.case["category"], lang=s.lang, removed_citations=rep, llm_calls=llm.calls - calls0)


def practice_feedback(s: Session, llm: LLM) -> Result:
    calls0 = llm.calls
    if not s.practice:
        return Result(reply="Practise first, then I can give feedback.", lang=s.lang)
    transcript = "\n".join(f"{'USER' if m['role'] == 'user' else 'OTHER SIDE'}: {m['content']}" for m in s.practice)
    try:
        raw = llm.chat(prompts.feedback_system(_case_json(s.case), s.case["category"], s.lang),
                       [{"role": "user", "content": "Practice transcript:\n" + transcript}], max_tokens=500)
    except LLMError as e:
        return Result(reply=f"Model error: {e}", error=str(e), lang=s.lang)
    clean, rep = G.check_reply(raw, s.lang)
    return Result(reply=clean, category=s.case["category"], lang=s.lang, removed_citations=rep, llm_calls=llm.calls - calls0)
