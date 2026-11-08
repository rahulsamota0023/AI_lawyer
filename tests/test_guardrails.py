"""Pure-code tests: no model, no network.   Run: pytest -q"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date

from core import case as C
from core import guardrails as G
from core import router


def removed(text):
    return G.check_reply(text)[1]


def test_keeps_verified_citations():
    t = "Under Section 69 of the Consumer Protection Act, 2019 you generally have 2 years. Section 69(2) allows late filing for sufficient cause."
    assert removed(t) == []
    assert "Section 69(2)" in G.check_reply(t)[0]


def test_removes_case_law():
    assert removed("As held in Sharma v. Union of India (AIR 2019 SC 1234), the landlord must refund.")[0]["type"] == "case_law"
    assert removed("The Supreme Court has held that deposits must be returned.")[0]["type"] == "case_law"


def test_removes_unknown_section_and_unknown_act():
    assert removed("Under Section 420 of the Indian Penal Code you can file a case.")
    assert removed("Section 99 of the Code on Wages, 2019 helps you.")[0]["type"] == "unverified_section"


def test_removes_article_numbers():
    assert removed("Under Article 113 of the Limitation Act you have three years.")


def test_repealed_act_only_ok_when_described_as_repealed():
    assert removed("Section 15 of the Payment of Wages Act, 1936 lets you claim your salary.")[0]["type"] == "repealed_act"
    assert removed("The Payment of Wages Act, 1936 has been repealed and replaced by the Code on Wages, 2019.") == []


def test_consumer_act_1986_is_not_confused_with_2019():
    assert removed("Section 69 of the Consumer Protection Act, 1986 gives two years.")[0]["type"] == "repealed_act"


def test_section_without_act_is_removed_but_carried_context_works():
    assert removed("Section 45 gives you 3 years.")[0]["type"] == "no_act"
    assert removed("Under the Code on Wages, 2019 the employer must pay. Section 45 lets you claim.") == []


def test_interest_rate_removed():
    assert removed("You are entitled to interest at 18% per annum by law.")[0]["type"] == "interest_rate"


def test_abbreviations_do_not_break_sentence_splitting():
    t = "Rs. 50,000 is owed. Sec. 69 of the Consumer Protection Act, 2019 says 2 years."
    assert removed(t) == []


def test_hindi_marker_used_for_hindi():
    clean, rep = G.check_reply("As held in Rao v. State (2020) 5 SCC 100, you win.", lang="hi")
    assert rep and "वकील" in clean


def test_escalation_rules():
    code = lambda s, cat=None: [f["code"] for f in G.pre_check(s, cat)]
    assert code("I feel like I want to die") == ["self_harm"]
    assert code("he threatened to beat me") == ["violence"]
    assert code("my brother needs bail") == ["out_of_scope"]
    assert G.pre_check("my brother needs bail", "tenancy")[0]["level"] == "soft"   # keeps helping with the in-scope part
    assert "received_notice" in code("I received a legal notice", "tenancy")
    assert "received_notice" not in code("I will send a legal notice", "tenancy")
    assert code("मेरा भाई गिरफ्तार हो गया") == ["out_of_scope"]
    assert code("मुझे जान से मारने की धमकी दी") == ["violence"]


def test_limitation_clock():
    c = C.empty_case(); c["category"] = "consumer"; c["event_date"] = "2024-11-20"
    st = C.limitation_status(c, date(2026, 11, 7))
    assert st["level"] == "near" and st["deadline"] == "2026-11-20"
    c["event_date"] = "2023-05-10"
    assert C.limitation_status(c, date(2026, 11, 7))["level"] == "expired"
    c["category"] = "tenancy"; c["vacated_date"] = "2026-09-15"
    assert C.limitation_status(c, date(2026, 11, 7))["level"] == "ok"


def test_merge_rejects_bad_llm_output():
    c = C.empty_case()
    C.merge_updates(c, {"amount": "-5", "event_date": "yesterday", "category": "criminal", "hack": "x", "proof": "a receipt"})
    assert c["amount"] is None and c["event_date"] is None and c["category"] is None and c["proof"] == ["a receipt"]
    C.merge_updates(c, {"amount": "1,20,000", "event_date": "2026-09"})
    assert c["amount"] == 120000 and c["event_date"] == "2026-09-01"


def test_routing_and_language():
    assert router.classify_rules("landlord ne deposit wapas nahi diya")[0] == "tenancy"
    assert router.classify_rules("my salary is unpaid")[0] == "wages"
    assert router.classify_rules("amazon refund defective phone")[0] == "consumer"
    assert router.classify_rules("hello")[0] is None
    assert router.detect_lang("मेरी सैलरी नहीं मिली") == "hi"
    assert router.detect_lang("mera deposit nahi mila, landlord bol raha hai") == "hinglish"
    assert router.detect_lang("my deposit is not returned") == "en"


def test_every_kb_section_is_checkable():
    """Each section stored in the KB must pass the checker when cited with its act name, else the KB would block itself."""
    from core import kb
    for t in kb.topics().values():
        for p in t["provisions"]:
            for sec in p["sections"]:
                name = kb.acts()[p["act_key"]]["name"]
                assert G.check_reply(f"Section {sec} of the {name} applies.")[1] == [], (p["id"], sec)


def test_notice_free_text_cannot_smuggle_citations():
    from core import notice
    c = C.empty_case(); c["category"] = "tenancy"; c["amount"] = 50000
    c["what_happened"] = "He kept my money. Under Section 420 of the Indian Penal Code he is a cheat. As held in Rao v. State (2020) 5 SCC 100 I win."
    docs = notice.build_documents(c, date(2026, 11, 7))
    body = docs[0]["body"]
    assert "420" not in body and "SCC" not in body and "He kept my money." in body
    assert len(docs[0]["removed_citations"]) == 2


def test_every_template_only_cites_verified_provisions():
    from core import notice
    for cat in ("tenancy", "consumer", "wages"):
        c = C.empty_case(); c["category"] = cat; c["amount"] = 1000; c["mta_applies"] = True; c["still_employed"] = False
        for d in notice.build_documents(c, date(2026, 11, 7)):
            assert G.check_reply(d["body"])[1] == [], (cat, d["title"])


# ---- provider plumbing (no network: requests.post is faked with each provider's documented response shape)
class _Resp:
    def __init__(self, status, payload): self.status_code, self._p, self.text = status, payload, str(payload)
    def json(self): return self._p


def test_provider_parsers_and_error_handling(monkeypatch):
    import requests
    from core.llm import LLM, LLMError, strip_json
    seen = {}

    def fake(url, headers=None, json=None, timeout=None):
        seen["url"], seen["headers"], seen["body"] = url, headers, json
        if "generativelanguage" in url:
            return _Resp(200, {"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]}}]})
        if "anthropic" in url:
            return _Resp(200, {"content": [{"type": "text", "text": "hello"}]})
        return _Resp(200, {"choices": [{"message": {"content": "hi"}}]})
    monkeypatch.setattr(requests, "post", fake)
    g = LLM("gemini", api_key="k"); assert strip_json(g.chat("sys", [{"role": "user", "content": "x"}], json_mode=True)) == {"a": 1}
    assert seen["headers"]["x-goog-api-key"] == "k" and seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    a = LLM("anthropic", api_key="k"); assert a.chat("sys", [{"role": "user", "content": "x"}]) == "hello"
    assert seen["body"]["system"] == "sys" and seen["headers"]["anthropic-version"]
    o = LLM("openai", api_key="k"); assert o.chat("sys", [{"role": "user", "content": "x"}]) == "hi"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(429, {"error": "quota"}))
    monkeypatch.setattr("time.sleep", lambda s: None)
    import pytest
    with pytest.raises(LLMError, match="quota"):
        LLM("gemini", api_key="k").chat("s", [{"role": "user", "content": "x"}])
    with pytest.raises(LLMError, match="No API key"):
        LLM("openai", api_key="").chat("s", [{"role": "user", "content": "x"}])


def test_strip_json_handles_fences_and_chatter():
    from core.llm import strip_json
    assert strip_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert strip_json('Sure! Here you go: {"a": 3} hope that helps') == {"a": 3}
    assert strip_json("not json") is None


def test_engine_survives_garbage_model_output():
    """If the extraction call returns junk, the turn must not crash and must not corrupt the case card."""
    from core.engine import Session, process_turn
    from core.llm import LLM
    llm = LLM("mock")
    orig = llm._mock.chat
    llm._mock.chat = lambda system, messages, json_mode=False: "I am sorry, I cannot do that" if system.startswith("[TASK:EXTRACT]") else orig(system, messages, json_mode)
    s = Session(today=date(2026, 11, 7))
    r = process_turn(s, "my landlord kept my deposit", llm)
    assert r.reply and r.category == "tenancy" and s.case["amount"] is None


SNEAKY = ["IPC 420 applies here.", "You can file under 138 NI Act for the bounced cheque.", "Sec 138 of the NI Act applies.",
          "Courts have consistently ruled that landlords must refund within 30 days.", "Under the Indian Contract Act you can claim damages.",
          "The Consumer Protection Act lets you claim ten times the price as compensation.", "BNS 318 covers cheating.",
          "Section 11 of the Model Tenancy Act, 2021 caps the deposit at 5 months.",
          "Section 69 of the Consumer Protection Act, 2019 gives you 5 years.", "Section 45 of the Code on Wages, 2019 gives you 6 months to claim."]
BENIGN = ["Under Section 69 of the Consumer Protection Act, 2019 you generally have 2 years to file.",
          "Under Section 17 of the Code on Wages, 2019 wages must be paid within 2 working days of resigning.",
          "Section 11 of the Model Tenancy Act, 2021 caps a residential deposit at two months' rent.",
          "The Code on Wages, 2019 lets the authority order up to ten times the wages owed as compensation.",
          "The District Commission hears claims up to Rs 50 lakh.", "Keep a copy of every message and send the notice by registered post."]


def test_sneaky_citations_and_wrong_figures_are_caught():
    for t in SNEAKY:
        assert removed(t), t


def test_correct_statements_survive():
    for t in BENIGN:
        assert removed(t) == [], t


def test_users_own_figures_are_not_flagged():
    t = "You said 3 months of salary is unpaid, and the Code on Wages, 2019 makes the employer responsible."
    assert G.check_reply(t, user_text="my salary is unpaid for 3 months")[1] == []
    assert G.check_reply(t)[1] != []   # without that context the same figure is unverifiable
