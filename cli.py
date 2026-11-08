"""Terminal / Colab version.   python cli.py --provider gemini
Commands: /card  /draft  /practice  /end  /quit"""
import argparse
import json

from core import notice
from core.engine import Session, practice_feedback, practice_turn, process_turn
from core.llm import LLM

ap = argparse.ArgumentParser()
ap.add_argument("--provider", default=None)
ap.add_argument("--model", default=None)
a = ap.parse_args()
llm = LLM(a.provider, a.model)
s = Session()
print(f"Nyay Saathi ({llm.provider}). I'm an AI, not a lawyer. Commands: /card /draft /practice /end /quit\n")
while True:
    try:
        t = input("you> ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not t:
        continue
    if t == "/quit":
        break
    if t == "/card":
        print(json.dumps({k: v for k, v in s.case.items() if v not in (None, [])}, ensure_ascii=False, indent=1)); continue
    if t == "/draft":
        for d in notice.build_documents(s.case, s.today):
            print(f"\n===== {d['title']} ({d['placeholders']} gaps) =====\n{d['body']}")
        continue
    if t == "/practice":
        s.practice_on, s.practice = True, []; print("[practice mode: I play the other side. /end to finish]"); continue
    if t == "/end":
        s.practice_on = False; print(practice_feedback(s, llm).reply); continue
    r = practice_turn(s, t, llm) if s.practice_on else process_turn(s, t, llm)
    print("\n" + r.reply)
    for f in ([] if s.practice_on else r.flags):
        if f.get("text"):
            print(f"\n[!] {f['text']}")
    if r.removed_citations:
        print(f"\n[shield] removed {len(r.removed_citations)} unverified citation(s)")
    print()
