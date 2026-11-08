"""Nyay Saathi: a plain-language legal helper for everyday problems in India (Streamlit UI)."""
import hashlib
import json
import os

import streamlit as st

from core import case as C
from core import kb, notice
from core.engine import Session, practice_feedback, practice_turn, process_turn
from core.llm import DEFAULT_MODELS, KEY_ENV, LLM

st.set_page_config(page_title="Nyay Saathi: AI legal helper", page_icon="⚖️", layout="wide")


def secret(name, default=""):
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)


# ---------------------------------------------------------------- state
if "s" not in st.session_state:
    st.session_state.s = Session()
    st.session_state.msgs = []          # chat bubbles
    st.session_state.practice_msgs = []
    st.session_state.docs = []
    st.session_state.last_audio = None

s: Session = st.session_state.s

# ---------------------------------------------------------------- sidebar: swappable model
with st.sidebar:
    st.header("⚙️ Model")
    options = ["gemini", "anthropic", "openai", "mock"]
    default = secret("LLM_PROVIDER") or ("gemini" if secret("GEMINI_API_KEY") else "mock")
    provider = st.selectbox("Provider", options, index=options.index(default) if default in options else 3,
                            help="Swap models in one click. 'mock' is an offline demo with no AI.")
    model = st.text_input("Model name", value=secret("LLM_MODEL") or DEFAULT_MODELS.get(provider, ""), disabled=provider == "mock")
    key = ""
    if provider != "mock":
        key = st.text_input(f"{KEY_ENV[provider]}", value=secret(KEY_ENV[provider]), type="password",
                            help="Stays in this browser session. Never stored by the app.")
    llm = LLM(provider, model or None, key or None)
    if llm.is_mock:
        st.warning("Offline demo mode: replies are templated from the knowledge base, NOT written by an AI. Rules, citation checks and papers are real.")
    st.divider()
    st.caption("**Covers:** rental deposit not returned · refund / defective product or service · unpaid salary.\n\n"
               "**Does not cover:** criminal/police matters, family, property, eviction, tax, cheque bounce. Those get a 'see a lawyer' response.")
    st.caption("Knowledge base last verified: " + kb.load()["common"]["verified_on"])
    if st.button("🔄 Start a new case"):
        st.session_state.clear()
        st.rerun()

# ---------------------------------------------------------------- header
st.title("⚖️ Nyay Saathi")
st.caption("Tell me your problem in Hindi, English or Hinglish. I'll organise your case, explain where you stand, and prepare the papers. "
           "**I'm an AI, not a lawyer. This is general information, not legal advice.**")

col_chat, col_side = st.columns([3, 2], gap="large")


def show_msg(m):
    with st.chat_message(m["role"]):
        st.markdown(m["text"])
        for f in m.get("flags", []):
            if f.get("text"):
                (st.error if f["code"] in ("limitation_expired", "limitation_near") else st.warning)(f["text"], icon="⚠️")
        if m.get("removed"):
            with st.expander(f"🛡️ {len(m['removed'])} unverified legal citation(s) were removed from this reply"):
                for r in m["removed"]:
                    st.caption(f"**{r['type']}**: {r['detail']}")


with col_chat:
    msgs = st.session_state.practice_msgs if s.practice_on else st.session_state.msgs
    if s.practice_on:
        st.info("🎭 **Practice mode**: I'm playing the other side so you can rehearse. Type as you would speak to them.")
    if not msgs and not s.practice_on:
        st.info("Example: *My landlord is not returning my ₹40,000 deposit. I left the flat on 15 Sept 2026.* "
                "Or: *मेरी तीन महीने की सैलरी नहीं मिली।*")
    for m in msgs:
        show_msg(m)

# ---------------------------------------------------------------- side panel: case card, papers, practice
with col_side:
    st.subheader("📋 Your case card")
    cat = s.case.get("category")
    if not cat:
        st.caption("Nothing yet. It fills in as we talk.")
    else:
        t = kb.topic(cat)
        st.markdown(f"**{t['title']}**")
        labels = {"other_party_name": "Other party", "amount": "Amount (₹)", "event_date": "Key date", "vacated_date": "Vacated on",
                  "product_or_service": "Product/service", "complained_to_seller": "Already complained", "still_employed": "Still employed",
                  "what_happened": "What happened", "proof": "Proof you have", "state": "State"}
        for f in t["required_fields"]:
            v = s.case.get(f)
            shown = "✅ " + (", ".join(v) if isinstance(v, list) else str(v)) if v not in (None, []) else "⬜ *still needed*"
            st.markdown(f"- **{labels.get(f, f)}**: {shown}")
        lim = C.limitation_status(s.case, s.today)
        if lim["level"] != "unknown":
            icon = {"ok": "🟢", "near": "🟠", "expired": "🔴"}[lim["level"]]
            st.markdown(f"{icon} **Time limit** (about {lim['years']} yrs): around **{lim['deadline']}** ({lim['days_left']} days left)" if lim["days_left"] >= 0
                        else f"🔴 **Time limit** seems to have passed around **{lim['deadline']}**")
        with st.expander("Correct or add details yourself"):
            for f in ("user_name", "user_address", "other_party_address", "property_address", "state"):
                new = st.text_input(f.replace("_", " ").title(), value=s.case.get(f) or "", key=f"edit_{f}")
                if new and new != (s.case.get(f) or ""):
                    s.case[f] = new
            if cat == "tenancy":
                s.case["mta_applies"] = st.checkbox("My state has adopted the Model Tenancy Act, 2021", value=bool(s.case.get("mta_applies")))

    st.subheader("📄 Papers")
    if st.button("Prepare draft papers", disabled=not cat, use_container_width=True):
        st.session_state.docs = notice.build_documents(s.case, s.today)
    for i, d in enumerate(st.session_state.docs):
        with st.expander(f"{d['title']}  ({d['placeholders']} gap(s) to fill)", expanded=i == 0):
            if d["placeholders"]:
                st.caption("Gaps are marked [FILL: ...]. Complete them before sending.")
            edited = st.text_area("Edit freely", d["body"], height=380, key=f"doc_{i}")
            st.download_button("⬇️ Download .txt", edited, file_name=f"{cat}_{i + 1}.txt", key=f"dl_{i}")
    if st.session_state.docs:
        st.caption("These papers are templates filled with your facts. A lawyer should review anything high-stakes.")

    st.subheader("🎭 Practice")
    if not s.practice_on:
        if st.button("Practise with the other side", disabled=not cat, use_container_width=True,
                     help="The AI plays your landlord / employer / seller so you can rehearse."):
            s.practice_on = True
            s.practice = []
            st.session_state.practice_msgs = []
            st.rerun()
    else:
        if st.button("End practice & get feedback", use_container_width=True):
            with st.spinner("Thinking..."):
                r = practice_feedback(s, llm)
            s.practice_on = False
            st.session_state.msgs.append({"role": "assistant", "text": "**Practice feedback**\n\n" + r.reply, "removed": r.removed_citations})
            st.rerun()

# ---------------------------------------------------------------- input (text, plus optional voice)
user_text = st.chat_input("Type your problem here…")

if hasattr(st, "audio_input") and provider == "gemini":
    with col_chat:
        audio = st.audio_input("🎙️ Or speak (optional, Gemini only)")
    if audio is not None:
        data = audio.getvalue()
        h = hashlib.md5(data).hexdigest()
        if h != st.session_state.last_audio:
            st.session_state.last_audio = h
            try:
                with st.spinner("Listening…"):
                    user_text = llm.transcribe(data, audio.type or "audio/wav")
                st.toast(f"Heard: {user_text}")
            except Exception as e:  # voice is a bonus path; never break text chat
                st.warning(f"Could not transcribe audio: {e}")

if user_text:
    bubbles = st.session_state.practice_msgs if s.practice_on else st.session_state.msgs
    bubbles.append({"role": "user", "text": user_text})
    with st.spinner("Thinking…"):
        r = practice_turn(s, user_text, llm) if s.practice_on else process_turn(s, user_text, llm)
    bubbles.append({"role": "assistant", "text": r.reply, "removed": r.removed_citations,
                    "flags": [] if s.practice_on else r.flags})
    if not s.practice_on and s.turns == 1 and not r.stopped_by_rule:
        bubbles[-1]["text"] += "\n\n*ℹ️ " + kb.load()["common"]["disclaimer_hi" if r.lang == "hi" else "disclaimer_en"] + "*"
    st.rerun()
