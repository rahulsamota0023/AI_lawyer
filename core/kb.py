"""Loads the hand-verified knowledge base. Adding a new problem type = adding one JSON file in kb/."""
import glob
import json
import os
from functools import lru_cache

KB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kb")


@lru_cache(maxsize=1)
def load():
    with open(os.path.join(KB_DIR, "acts.json"), encoding="utf-8") as f:
        acts = {a["key"]: a for a in json.load(f)}
    with open(os.path.join(KB_DIR, "common.json"), encoding="utf-8") as f:
        common = json.load(f)
    topics = {}
    for path in sorted(glob.glob(os.path.join(KB_DIR, "*.json"))):
        name = os.path.basename(path)
        if name in ("acts.json", "common.json"):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        topics[data["topic"]] = data
    return {"acts": acts, "common": common, "topics": topics}


def topics():
    return load()["topics"]


def topic(name):
    return load()["topics"].get(name)


def acts():
    return load()["acts"]


def allowed_sections():
    """{act_key: set(section strings)} across every provision in every topic file."""
    out = {}
    for t in topics().values():
        for p in t["provisions"]:
            out.setdefault(p["act_key"], set()).update(s.replace(" ", "").lower() for s in p["sections"])
    return out


def kb_acts_with_provisions():
    return set(allowed_sections().keys())


def render_provisions(topic_name):
    """Text block injected into the prompt. The model may cite ONLY these."""
    t = topic(topic_name)
    if not t:
        return "(none)"
    lines = []
    for p in t["provisions"]:
        flag = "" if p["verified"] is True else "  [PARTLY VERIFIED - hedge: say 'generally' / 'please confirm']"
        lines.append(f"[{p['id']}] {p['cite_as']}{flag}\n  {p['plain']}")
        if p.get("caveat"):
            lines.append(f"  CAVEAT: {p['caveat']}")
    return "\n".join(lines)


def render_procedure(topic_name):
    t = topic(topic_name)
    if not t:
        return ""
    steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(t["procedure"]["steps"]))
    return f"{t['procedure']['title']}:\n{steps}"


def render_helplines():
    c = load()["common"]
    return "\n".join(f"- {h['name']}: {h['number']}" for h in c["helplines"])
