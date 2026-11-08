"""Run every test case through the full pipeline and save UNEDITED outputs + a scorecard.

    python run_tests.py --provider gemini        # real model (needs GEMINI_API_KEY)
    python run_tests.py --provider anthropic
    python run_tests.py --provider mock          # offline: tests the rules/KB/templates, NOT language quality
    python run_tests.py --provider mock-trap     # offline: model deliberately 'misbehaves' to prove the citation checker
"""
import argparse
import json
import os
import re
import sys
from datetime import date

from core import guardrails as G
from core import notice, router
from core.engine import Session, process_turn
from core.llm import LLM

TODAY = date(2026, 11, 7)  # fixed so limitation results are reproducible


def run_case(case, llm):
    s = Session(today=TODAY)
    turns = []
    for user in case["turns"]:
        r = process_turn(s, user, llm)
        turns.append({"user": user, "reply": r.reply, "stopped_by_rule": r.stopped_by_rule,
                      "flags": [{"code": f["code"], "level": f["level"], "text": f.get("text", "")} for f in r.flags],
                      "removed_citations": r.removed_citations, "missing_fields": r.missing,
                      "limitation": r.limitation, "ready_to_draft": r.ready_to_draft, "llm_calls": r.llm_calls,
                      "error": r.error})
    docs = notice.build_documents(s.case, TODAY) if s.case.get("category") and not turns[-1]["stopped_by_rule"] else []
    return {"id": case["id"], "title": case["title"], "provider": llm.provider, "model": llm.model, "turns": turns,
            "final_case_card": s.case, "documents": docs}


def score(case, out, provider):
    exp, turns = case["expect"], out["turns"]
    last = turns[-1]
    flags = {f["code"] for t in turns for f in t["flags"]}
    hard = next((f["code"] for t in turns for f in t["flags"] if f["level"] == "hard"), None)
    res = {}
    res["category"] = out["final_case_card"].get("category") == exp.get("category")
    res["escalation"] = hard == exp.get("hard") and all(c in flags for c in exp.get("soft", [])) and not any(c in flags for c in exp.get("not_flags", []))
    res["citations_clean"] = all(not G.check_reply(t["reply"])[1] for t in turns)  # nothing unverifiable survives to the user
    if provider == "mock-trap":
        reached_llm = any(not t["stopped_by_rule"] for t in turns)
        res["trap_stripped"] = (sum(len(t["removed_citations"]) for t in turns) >= 3) if reached_llm else None
    if "limitation" in exp:
        res["limitation"] = last["limitation"].get("level") == exp["limitation"]
    if exp.get("lang") == "hi":
        fixed = [t for t in turns if t["stopped_by_rule"]]
        if fixed or provider.startswith("mock"):
            res["language"] = None if not fixed else all(router.devanagari_ratio(t["reply"]) > 0.3 for t in fixed)
        else:
            res["language"] = all(router.devanagari_ratio(t["reply"]) > 0.3 for t in turns)
    if "ready" in exp:
        res["ready_to_draft"] = (last["ready_to_draft"] == exp["ready"]) if provider.startswith("mock") else None  # info only for real models
    return res


def md_transcript(case, out):
    L = [f"# {out['id']}: {out['title']}", f"provider: `{out['provider']}`  model: `{out['model']}`", ""]
    for i, t in enumerate(out["turns"], 1):
        L += [f"## Turn {i}", "**User:**", "", t["user"], "", "**Assistant:**", "", t["reply"], ""]
        for f in t["flags"]:
            L.append(f"- FLAG `{f['code']}` ({f['level']}): {f['text']}" if f["text"] else f"- FLAG `{f['code']}` ({f['level']}) - fixed message shown above")
        for r in t["removed_citations"]:
            L.append(f"- CITATION REMOVED `{r['type']}`: {r['detail']}  | text was: \"{r['removed_text']}\"")
        L += ["", f"missing fields: {t['missing_fields']} | limitation: {t['limitation'].get('level', '-')} {t['limitation'].get('deadline', '')} | ready_to_draft: {t['ready_to_draft']} | llm_calls: {t['llm_calls']}", ""]
    L += ["## Final case card", "```json", json.dumps({k: v for k, v in out["final_case_card"].items() if v not in (None, [])}, ensure_ascii=False, indent=1), "```"]
    for d in out["documents"]:
        L += ["", f"## Generated document: {d['title']}  ({d['placeholders']} [FILL] gaps)", "```", d["body"], "```"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=os.getenv("LLM_PROVIDER", "mock"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", default=None, help="run a single case id prefix, e.g. T05")
    a = ap.parse_args()
    cases = json.load(open("tests/cases.json", encoding="utf-8"))
    if a.only:
        cases = [c for c in cases if c["id"].startswith(a.only)]
    llm = LLM(a.provider, a.model)
    outdir = os.path.join("raw_outputs", a.provider.replace("-", "_"))
    os.makedirs(outdir, exist_ok=True)
    rows, total_calls = [], 0
    for c in cases:
        out = run_case(c, llm)
        sc = score(c, out, a.provider)
        out["scorecard"] = sc
        json.dump(out, open(f"{outdir}/{c['id']}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        open(f"{outdir}/{c['id']}.md", "w", encoding="utf-8").write(md_transcript(c, out))
        rows.append((c, sc, out))
        total_calls += sum(t["llm_calls"] for t in out["turns"])
        print(f"{c['id']:34s}", {k: ("PASS" if v else "FAIL") for k, v in sc.items() if v is not None})
    checks = sorted({k for _, sc, _ in rows for k in sc})
    lines = [f"# Scorecard: provider `{a.provider}` model `{llm.model}`  (today fixed at {TODAY})", ""]
    if a.provider.startswith("mock"):
        lines += ["> **Offline run.** No language model was used. This tests the code layers (routing, escalation rules, limitation clock, "
                  "knowledge base, citation checker, templates). It says NOTHING about answer quality. Re-run with a real provider for that.", ""]
    lines += ["| case | " + " | ".join(checks) + " |", "|---|" + "---|" * len(checks)]
    sym = {True: "PASS", False: "FAIL", None: "-"}
    passed = failed = 0
    for c, sc, _ in rows:
        lines.append(f"| {c['id']} | " + " | ".join(sym[sc.get(k)] for k in checks) + " |")
        passed += sum(1 for v in sc.values() if v is True)
        failed += sum(1 for v in sc.values() if v is False)
    lines += ["", f"**{passed} checks passed, {failed} failed.** LLM calls used: {total_calls}."]
    open(f"{outdir}/SCORECARD.md", "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines[-2:]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
