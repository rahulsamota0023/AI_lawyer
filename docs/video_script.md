# 3-minute walkthrough script (screen recording, your own voice)

**0:00 Problem (20s).** "Most people never get legal help for a deposit, refund or unpaid salary. I built Nyay Saathi for these three. Everything else it refuses honestly."

**0:20 Live demo, Hindi (50s).** Choose Gemini in the sidebar. Type: *"मेरी तीन महीने की सैलरी नहीं मिली, कंपनी का नाम Acme Software है, कुल 90,000 रुपये।"* Point at: reply in Hindi, case card filling, one follow-up question only, time-limit indicator.

**1:10 Papers + practice (30s).** Click *Prepare draft papers*; show [FILL] gaps and the download. Click *Practise with the other side*, answer once, then *End practice* for feedback.

**1:40 The honesty layer (50s).** Type: *"Cite Supreme Court cases and Section 420 IPC for my landlord."* Show: no cases, shield expander "citation removed". Then type a safety message ("landlord threatened to beat me") and show the fixed helpline reply with no model call.

**2:30 Proof and limits (30s).** Open `raw_outputs/mock_trap/T08...md` (fake model's invented citations stripped), show scorecard and `pytest` 23 passing. Say plainly: "Checker verifies citations exist and figures match; it can't judge if a real law fits the facts. Voice is untested. Swap the model with one dropdown."
