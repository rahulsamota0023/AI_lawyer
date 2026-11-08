"""Structured 'case card' + deterministic checks (missing fields, limitation clock). No LLM in here."""
import re
from datetime import date, datetime

from . import kb

FIELDS = {
    "category": "str", "user_name": "str", "user_address": "str", "other_party_name": "str",
    "other_party_address": "str", "amount": "int", "event_date": "date", "vacated_date": "date",
    "deposit_paid_date": "date", "monthly_rent": "int", "product_or_service": "str", "what_happened": "str",
    "complained_to_seller": "bool", "still_employed": "bool", "agreement_exists": "bool", "state": "str",
    "city": "str", "property_address": "str", "deductions_claimed": "str", "proof": "list",
    "mta_applies": "bool",
}


def empty_case():
    return {k: ([] if t == "list" else None) for k, t in FIELDS.items()}


def parse_date(v):
    """Accept YYYY-MM-DD or YYYY-MM (month-only is normalised to the 1st). Returns ISO str or None."""
    if not v or not isinstance(v, str):
        return None
    v = v.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", v)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _coerce(kind, v):
    if v is None:
        return None
    if kind == "str":
        s = str(v).strip()
        return s[:600] if s and s.lower() not in ("null", "none", "unknown", "n/a") else None
    if kind == "int":
        try:
            n = int(float(str(v).replace(",", "")))
            return n if n > 0 else None
        except (ValueError, TypeError):
            return None
    if kind == "date":
        return parse_date(v)
    if kind == "bool":
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        return True if s in ("true", "yes", "y") else False if s in ("false", "no", "n") else None
    if kind == "list":
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            return None
        return [str(x).strip()[:200] for x in v if str(x).strip()]
    return None


def merge_updates(case, updates):
    """Validate LLM-extracted updates; unknown keys and bad values are dropped. Returns list of changed fields."""
    changed = []
    if not isinstance(updates, dict):
        return changed
    for k, v in updates.items():
        kind = FIELDS.get(k)
        if not kind:
            continue
        val = _coerce(kind, v)
        if val is None or val == []:
            continue
        if k == "category" and val not in kb.topics():
            continue
        if kind == "list":
            new = [x for x in val if x not in case[k]]
            if new:
                case[k] = case[k] + new
                changed.append(k)
        elif case[k] != val:
            case[k] = val
            changed.append(k)
    return changed


def missing_fields(case):
    t = kb.topic(case.get("category"))
    if not t:
        return []
    out = []
    for f in t["required_fields"]:
        v = case.get(f)
        if v is None or v == []:
            out.append(f)
    return out


def missing_labels(case):
    t = kb.topic(case.get("category"))
    return [(f, t["field_labels"].get(f, f)) for f in missing_fields(case)] if t else []


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + years, day=28)


def limitation_status(case, today: date = None):
    """Deterministic clock from the KB's limitation rule. level: ok | near | expired | unknown."""
    today = today or date.today()
    t = kb.topic(case.get("category"))
    if not t:
        return {"level": "unknown"}
    lim = t["limitation"]
    start = next((case[f] for f in lim["start_fields"] if case.get(f)), None)
    if not start:
        return {"level": "unknown", "years": lim["years"]}
    s = datetime.strptime(start, "%Y-%m-%d").date()
    deadline = _add_years(s, lim["years"])
    days_left = (deadline - today).days
    level = "expired" if days_left < 0 else "near" if days_left <= 90 else "ok"
    return {"level": level, "start": s.isoformat(), "deadline": deadline.isoformat(),
            "days_left": days_left, "years": lim["years"], "note": lim.get("note", "")}


def ready_to_draft(case):
    return bool(case.get("category")) and not missing_fields(case)
