"""Offline stand-in for an LLM so the whole pipeline (rules, KB, citation checker, notices) can run with no key.
It is NOT a language model: replies are templated from the knowledge base. Outputs generated with it are labelled 'mock'.
'mock-trap' deliberately appends fake citations so the citation checker can be demonstrated end to end."""
import json
import re

_AMT = re.compile(r"(?:₹|rs\.?|inr|rupees?)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|k|thousand)?|([\d,]+(?:\.\d+)?)\s*(lakh|lac|लाख|k|thousand|rupees|रुपये|रुपए)", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_MONTHS = {m: i + 1 for i, m in enumerate("january february march april may june july august september october november december".split())}
_TXT = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", re.I)
_NAME = re.compile(r"(?:landlord|employer|company|seller|owner|shop)\s+(?:is\s+|named\s+|called\s+)?((?:Mr\.?|Mrs\.?|Ms\.?|M/s)\s*)?([A-Z][\w&.\-]+(?:\s+[A-Z][\w&.\-]+){0,3})")
_PROOF = [("whatsapp", "WhatsApp chats"), ("receipt", "receipt"), ("invoice", "invoice"), ("agreement", "rent agreement"),
          ("bank statement", "bank statement"), ("screenshot", "screenshots"), ("email", "emails"), ("payslip", "payslips"),
          ("offer letter", "offer letter"), ("chat", "chats"), ("bill", "bill"), ("photo", "photos"),
          ("रसीद", "रसीद"), ("एग्रीमेंट", "एग्रीमेंट"), ("स्क्रीनशॉट", "स्क्रीनशॉट")]

TRAP_TEXT = ("\n\nAs held in Sharma v. Union of India (AIR 2019 SC 1234), the other side must pay immediately. "
             "Under Section 420 of the Indian Penal Code you can also file a case. "
             "Section 15 of the Payment of Wages Act, 1936 lets you claim your salary. "
             "Interest at 18% per annum is payable by law.")


def _amount(text):
    best = 0
    for m in _AMT.finditer(text):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        u = (unit or "").lower()
        if u in ("lakh", "lac", "लाख"):
            v *= 100000
        elif u in ("k", "thousand"):
            v *= 1000
        best = max(best, int(v))
    return best or None


def _dates(text):
    out = [m.group(0) for m in _ISO.finditer(text)]
    out += [f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" for m in _DMY.finditer(text)]
    out += [f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}" for m in _TXT.finditer(text)]
    return out


class MockLLM:
    def __init__(self, trap=False):
        self.trap = trap

    def chat(self, system, messages, json_mode=False):
        task = re.match(r"\[TASK:(\w+)\]", system).group(1) if system.startswith("[TASK:") else "REPLY"
        last = messages[-1]["content"] if messages else ""
        return getattr(self, f"_{task.lower()}")(system, last, messages)

    def _extract(self, system, last, messages):
        out = {}
        known = last.split("User message:\n")[0]
        last = last.split("User message:\n")[-1]
        a = _amount(last)
        if a:
            out["amount"] = a
        ds = _dates(last)
        low = last.lower()
        if ds:
            if re.search(r"vacat|left the|moved out|handed over|खाली|छोड़", low):
                out["vacated_date"] = ds[0]
            else:
                out["event_date"] = ds[0]
        m = _NAME.search(last)
        if m:
            out["other_party_name"] = m.group(2).strip()
        proofs = [label for kw, label in _PROOF if kw in low and not (kw == "chat" and "whatsapp" in low)]
        if proofs:
            out["proof"] = proofs
        if re.search(r"no proof|nothing in writing", low):
            out["proof"] = ["none"]
        if re.search(r"\bstill (work|employed)|abhi bhi kaam", low):
            out["still_employed"] = True
        if re.search(r"resign|left the job|last working day|quit|छोड़ दी", low):
            out["still_employed"] = False
        if re.search(r"complained|emailed them|called (them|customer)|raised a ticket|asked (them|him|her) for", low):
            out["complained_to_seller"] = True
        if re.search(r"bought|ordered|purchase|खरीद", low):
            out["product_or_service"] = last[:80]
        if '"what_happened"' not in known:
            out["what_happened"] = last[:400]
        return json.dumps(out, ensure_ascii=False)

    def _classify(self, system, last, messages):
        return json.dumps({"category": "unknown"})

    def _clarify(self, system, last, messages):
        text = "[offline demo] Could you tell me a little more about what happened? Is it about a rental deposit, a refund for a product/service, or unpaid salary?"
        return text + (TRAP_TEXT if self.trap else "")

    def _reply(self, system, last, messages):
        block = system.split("ALLOWED PROVISIONS:\n", 1)[-1].split("\nPROCEDURE:", 1)[0]
        missing = re.search(r"MISSING \(ask for the first one only\): (.*)", system).group(1).strip()
        items = re.findall(r"\[(\w+)\] ([^\n]+)\n  ([^\n]+)", block)
        lines = ["[offline demo: templated from the knowledge base, not a language model] Here is what I can tell you in general terms:"]
        for _id, cite, plain in items[:3]:
            cite = re.sub(r"\s*\[PARTLY.*$", "", cite)
            lines.append(f"- {plain} ({cite})")
        if missing and missing != "nothing":
            label = missing.split(",")[0].split("=", 1)[-1].strip()
            lines.append(f"To prepare your papers, could you tell me {label}?")
        else:
            lines.append("Your case card is complete. You can now generate the draft notice below.")
        text = "\n".join(lines)
        return text + (TRAP_TEXT if self.trap else "")

    def _roleplay(self, system, last, messages):
        text = "[offline demo role-play] I understand you want your money back, but there were damages and paperwork takes time. What proof do you actually have?"
        return text + (" As held in Rao v. State (2020) 5 SCC 100, tenants lose such cases." if self.trap else "")

    def _feedback(self, system, last, messages):
        return ("[offline demo feedback] Strong: you stated the amount and dates clearly. Weak: you did not say what proof you hold. "
                "Bring: agreement, payment proof, and your written requests. Next time say calmly: 'Please share the deduction details in writing.'")
