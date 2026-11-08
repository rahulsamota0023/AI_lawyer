from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

H=ParagraphStyle("h",fontName="Helvetica-Bold",fontSize=11,leading=13.5,spaceBefore=8,spaceAfter=3,textColor=colors.HexColor("#1a3a5c"))
T=ParagraphStyle("t",fontName="Helvetica-Bold",fontSize=16,leading=19,spaceAfter=2)
B=ParagraphStyle("b",fontName="Helvetica",fontSize=9.3,leading=12.2,spaceAfter=3)
BL=ParagraphStyle("bl",parent=B,leftIndent=11,bulletIndent=1,spaceAfter=2.2)
S=ParagraphStyle("s",parent=B,fontSize=8.2,leading=10.4,textColor=colors.HexColor("#444444"))
C=ParagraphStyle("c",parent=B,fontSize=8.5,leading=10.8,spaceAfter=0)
def bl(t): return Paragraph(t,BL,bulletText="•")

story=[Paragraph("Nyay Saathi: an AI lawyer for everyday problems in India",T),
Paragraph("Problem 2 | Kuku AI Generalist Assignment | Name: ____  Roll no: ____  Branch: ____ | Prototype and raw outputs: see links in the form",S),
Paragraph("1. Why this problem, and how I scoped it",H),
Paragraph("The brief says one problem done well beats all of Indian law. I chose the three disputes ordinary people most often abandon, because each is a <b>money claim with a clear paper trail and a cheap forum</b>: (1) rental deposit not returned, (2) refund or defective product/service, (3) unpaid salary. Anything else (arrest, family, property, eviction, cheque bounce, tax) gets a fixed \"see a lawyer / free legal aid\" reply instead of a guess. Text input works in Hindi, English or Hinglish; voice is an optional Gemini-based extra that I did <b>not</b> test.",B),
Paragraph("2. Assumptions I made (no questions allowed)",H),
bl("Users are laypeople; the goal is to <b>act</b> (send a notice, file a complaint), not to learn law. Notices are generated in English, which Indian forums expect, while the chat stays in the user's language."),
bl("Where sources disagreed I took the official or latest one and hedged the rest. Example: many sites still print the old consumer-forum limits (District up to Rs 1 crore); the 2021 Jurisdiction Rules (30 Dec 2021) cut it to Rs 50 lakh, so the knowledge base uses Rs 50 lakh and says why."),
bl("Salary claims fall under the Code on Wages, 2019, in force since 21 Nov 2025 (it repealed the Payment of Wages Act, 1936). Wages that fell due earlier trigger a lawyer warning. State rules and offices vary, so the bot says so rather than naming one."),
bl("The Model Tenancy Act, 2021 is only a model law. The bot never says its 2-month deposit cap applies unless the user confirms their state adopted it."),
Paragraph("3. How it works and how it avoids inventing law",H),
Paragraph("Each turn: <b>rules</b> detect language and problem type and run escalation checks <i>before</i> any model call; the <b>LLM</b> extracts facts into a case card (JSON, validated by code); <b>code</b> computes missing fields and the limitation clock; the <b>LLM</b> explains using only the knowledge-base text injected into its prompt; <b>code</b> then audits the reply. Legal papers come from fixed templates, not from the model.",B),
bl("<b>Hand-verified knowledge base</b> (JSON). 15 provisions, each with a source URL and a verified / partly-verified flag, researched on 7 Nov 2026. Partly-verified ones are stated with hedges. Adding a problem type = one new JSON file plus one template."),
bl("<b>Citation checker (code, no LLM).</b> Removes any sentence that cites a section not in the KB, a case name or reporter, a repealed Act as current law, a court \"has held\", an invented interest rate, or a number-with-unit (\"5 months\", \"ten times\") that is not in the cited Act's verified text or in what the user said. Case law is never cited. The same checker also cleans the model's text before it is pasted into a notice."),
bl("<b>Escalation in code:</b> self-harm and violence (fixed safety message, helplines), out-of-scope topics, a notice already received, amount over Rs 5 lakh, consumer claim over Rs 50 lakh, wages older than the Code, and a limitation clock (2 yrs consumer; 3 yrs deposit and wages) that warns with under 90 days left or once passed."),
bl("<b>Swappable model:</b> one class over plain HTTPS; Gemini (free tier), Claude, OpenAI or an offline mock, via a sidebar dropdown or <font face='Courier'>LLM_PROVIDER</font>. Practice mode has the model play the landlord/employer (same citation filter), then coach the user."),
Paragraph("4. How I tested it, with honest results",H),
Paragraph("<b>What was actually run:</b> 23 unit tests (all pass) and 17 scenario cases: English, Hindi, Hinglish, vague, multi-turn, out-of-scope, violence, self-harm, time-barred, large claim, received notice, and three traps (repealed Act, \"cite Supreme Court cases\", prompt injection). Raw outputs and scorecards are in <font face='Courier'>raw_outputs/</font>.",B)]
rows=[["Run","Result","What it proves / does not"],
["Offline mock (no AI)","59/59 checks","Routing, escalation rules, limitation clock, KB and templates work. Says nothing about answer quality."],
["Offline mock-trap (a fake model that adds an invented case, IPC 420, a repealed Act and 18% interest)","73/73 checks","The citation checker strips all four fake types, in chat and in notices."],
["Real LLM (Gemini / Claude)","<b>NOT RUN in my build environment</b>","No key or network to Gemini there. Run <font face='Courier'>python run_tests.py --provider gemini</font> to produce real outputs. Language and follow-up quality are unmeasured until then."]]
t=Table([[Paragraph(c,C) for c in r] for r in rows],colWidths=[55*mm,32*mm,91*mm])
t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#999999")),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e8eef5")),("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
story+=[t,Spacer(1,2),
Paragraph("Where it fails (known)",H),
bl("<b>Checker limits.</b> It checks that a citation <i>exists</i> and that stated figures match the KB. It cannot judge whether a correct provision is <i>applied</i> correctly, or catch a wrong claim containing no section or figure. On 14 sneaky probes my first version missed 7; the final version missed 0, but I tuned it on that same set, so treat that as optimistic. It also over-removes: it deleted \"Landlord v. Tenant disputes are common\" (1 of 16 benign probes). I chose over-removal as the safe error."),
bl("<b>KB gaps.</b> Helpline numbers and the e-Daakhil URL are from memory, not re-verified. Section 17's 7th-day rule, the 50% deduction cap and the Section 2(7) wording come from secondary sources (flagged partly-verified). Fee slabs changed in 2022 and 2023, so the bot claims only \"nil up to Rs 5 lakh\". The Limitation Act Article for deposits is disputed across sources, so the bot gives no Article number."),
bl("<b>Not built or untested:</b> voice input; the Streamlit app was tested headlessly only, not deployed from my environment; Hinglish routing is keyword-based and will misroute unusual phrasing; no real-user testing."),
Paragraph("5. Scale, cost and the human in the loop",H),
Paragraph("<b>Cost.</b> Two model calls per turn (extract, reply), roughly 0.4k and 1.1-1.3k tokens of fixed prompt plus conversation history (my estimate from prompt length), with short outputs. A flash-class model keeps this to a small fraction of a rupee per conversation (compute from current prices). Routing, limits, escalation, citation audit and papers are free code.",B),
Paragraph("<b>To scale to many problem types.</b> A new topic is a JSON file. Verification is the real bottleneck, so each KB entry carries a source and a \"verified on\" date, and I would re-check on a schedule because laws change (the labour codes took effect only days before my knowledge cutoff).",B),
Paragraph("<b>Humans.</b> A paralegal reviews the KB and a weekly sample of flagged conversations; high-stakes cases (over Rs 5 lakh, received notices) are routed to a lawyer or NALSA legal aid. <b>Success in real use:</b> share of users who send a notice or file; zero unverified citations reaching users in audits; lawyer-reviewed correctness on a sample of 100 conversations.",B),
Paragraph("6. AI tools I used, and where they got it wrong",H),
Paragraph("I used Claude to research the law, write the code and tests, and draft this doc. <i>[Add any other tools you used, and what you edited yourself.]</i> <b>Where the AI was wrong:</b> (a) the first citation checker it wrote only verified that a section <i>existed</i>, so \"Section 11 of the Model Tenancy Act caps the deposit at 5 months\" passed; probing caught it and led to the figure check. (b) The offline mock read the \"Today's date\" header as the user's move-out date; the end-to-end smoke test caught it. (c) Web sources disagreed on consumer money limits and several still showed pre-2022 numbers; only the notified 2021 Rules settled it.",B)]
doc=SimpleDocTemplate("/mnt/user-data/outputs/Solution_Doc_AI_Lawyer.pdf",pagesize=A4,leftMargin=16*mm,rightMargin=16*mm,topMargin=13*mm,bottomMargin=12*mm,title="Nyay Saathi: AI lawyer solution doc")
doc.build(story)
from pypdf import PdfReader
r=PdfReader("/mnt/user-data/outputs/Solution_Doc_AI_Lawyer.pdf"); print("pages:",len(r.pages),[len(p.extract_text()) for p in r.pages])
