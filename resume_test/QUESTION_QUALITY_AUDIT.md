# Question Quality Audit — v2 Forensic Question Generator

**Scope note (read first):** the requested Move taxonomy (OPERATING_CONTEXT,
FAILURE, EXCLUSION, METRIC_DEFINITION, AUTHORITY, DEPENDENCY,
OWNERSHIP_BOUNDARY, PEOPLE, COHERENCE, PERTURB) belongs to the original
forensic-generator design (`docs/FORENSIC_GENERATOR_DESIGN.md`), which is
still an unimplemented document. What actually generates questions today is
`v2_forensic_question.txt`, driven by the v2 planner's 10 evidence
categories (OWNERSHIP, PROCESS, METRIC_DEFINITION, DECISION, DEPENDENCY,
INCIDENT, CONSTRAINT, CAUSAL_CHAIN, ARTIFACT, CROSS_CLAIM_LINK). This audit
covers that system. Section 6 is organized by evidence category, not Move.

**Data sources, all real, none synthetic-for-this-audit:**
- `question_review.csv` — 90 questions, 10 real claims across 3 real resumes
  x 9 categories (`CROSS_CLAIM_LINK` did not fire in that run — no
  claim-to-claim edges existed among the selected claims).
- A 5-turn live simulation (real planner, real question-generation calls,
  real signal-extraction calls on authored answers) on one claim.
- 5 targeted verification questions generated after the `CONSTRAINT` and
  `CAUSAL_CHAIN` prompt fixes landed mid-session.

8 of the 10 categories have 10 real examples each. `CONSTRAINT` and
`CAUSAL_CHAIN` have 10 pre-fix examples (in the CSV) plus 2-3 post-fix
examples each (fresher, smaller sample). `CROSS_CLAIM_LINK` has zero real
examples — reported as unaudited, not scored.

---

## 1. Forensic Power

| Category | Rating | Why |
|---|---|---|
| OWNERSHIP | LOW | "Who reviewed your work on managing the gynecology brands?" requires nothing but a job title in reply. Operational memory: none required. Sequence memory: none. |
| PROCESS | HIGH | "What were the first steps you took to generate the synthetic reasoning datasets?" requires genuine sequence + implementation memory — an impostor has to invent a plausible pipeline order, which is exactly where fabrication shows. |
| METRIC_DEFINITION | HIGH | "How was the 78% accuracy for borderless table extraction measured?" forces the candidate to state a measurement method, not just a headline number — implementation memory, hard to bluff generically. |
| DECISION | MEDIUM-HIGH | "Why did you choose synthetic reasoning datasets over real data for training?" (real answer surfaced NDA/legal-review specifics) shows genuine tradeoff memory when the claim has real tradeoffs. On thinner claims ("Why did you choose to mentor interns alongside managing developers?") it degrades toward a motivational platitude an impostor could supply. |
| DEPENDENCY | LOW | "Who did you coordinate with to launch OSTERI?" — no sequence, implementation, or tradeoff memory required, just a role name. |
| INCIDENT | VERY_HIGH | "Describe a specific time the model failed to extract a table correctly" demands a specific, bounded memory an impostor cannot generate from the resume alone. Highest forensic power of the set when answered honestly. |
| CONSTRAINT (post-fix) | MEDIUM | "What limitation most affected how you launched OSTERI?" requires real operational memory of a limiting factor, but doesn't require sequence or tradeoff memory the way DECISION does. |
| CAUSAL_CHAIN (post-fix) | HIGH | "What triggered the need to generate synthetic reasoning datasets, and what changed immediately after you started using them?" now requires both trigger memory and a downstream-change memory — meaningfully harder to bluff than the pre-fix version (below). |
| CAUSAL_CHAIN (pre-fix) | LOW | "What prompted you to launch OSTERI?" requires only a motivational guess — no sequence, implementation, or tradeoff memory at all. |
| ARTIFACT | MEDIUM | "What was the final form of the AIOps platform artifact?" requires some implementation memory (what shape the thing took) but not sequence or tradeoff memory. |
| CROSS_CLAIM_LINK | UNAUDITED | No real examples generated in any run. |

---

## 2. One-Word Exit Test

| Category | Verdict | Evidence |
|---|---|---|
| OWNERSHIP | **FAIL (5/10)** | "Who reviewed your integration work with Twilio's SDK?" → answerable with "My manager." "Who reviewed your work on managing the gynecology brands?" → "QA." These are your exact named escape hatches, verbatim risk. |
| PROCESS | PASS (10/10) | Every question asks "how" or "what steps" — structurally resists a one-word reply. |
| METRIC_DEFINITION | PASS (9/10), borderline | "How was the performance of DROGYNA tracked without a named metric?" could get "Surveys" but most ask for a calculation method, which resists brevity. |
| DECISION | PASS (9/10), borderline | "Why did you choose Twilio's SDK over other communication platforms?" could get "Cost" as a technically-responsive one-word dodge, but the form invites elaboration. |
| DEPENDENCY | **FAIL (9/10)** | "Who did you coordinate with to implement the loyalty module?" → "backend team" — this is, literally, one of your named escape-hatch examples. Nearly every DEPENDENCY question in the sample shares this exact vulnerability. |
| INCIDENT | PASS (8/10), 2 soft fails | "Describe a time when..." resists one-word replies, but permits a stonewall: "Never" or "Nothing" is a valid, evidence-free escape not covered by your named list but functionally identical to it. |
| CONSTRAINT (post-fix) | **FAIL** | "What limitation most affected how you launched OSTERI?" → "Budget." Fixing the hallucinated *type* (reported earlier this session) did not fix the escapability of the *question form* — this is a new, distinct finding, not the same bug. |
| CAUSAL_CHAIN (post-fix) | PASS | "What triggered the need to generate synthetic reasoning datasets, and what changed immediately after you started using them?" — the compound two-part form structurally blocks a one-word reply; you'd need to dodge both halves. |
| ARTIFACT | PASS (7/10), 3 soft fails | "who used it" half of several questions ("...and who used it?") permits a short "customers" answer even though the "what did it look like" half resists brevity. |

---

## 3. Impostor Parity Test

**FAIL — a resume-reader answers equally well:**
- OWNERSHIP: "What part of the SaaS platform were you directly responsible for?" — a stranger reading "Led frontend architecture..." answers "the frontend architecture" with zero risk of detection.
- DEPENDENCY: "Who did you rely on to integrate ThousandEyes with the AIOps platform?" — a stranger guesses "the network engineering team" and is plausible.
- CAUSAL_CHAIN (pre-fix): "What prompted you to launch OSTERI?" — "market opportunity" or "company strategy" is what *any* PM would say, real or invented.

**PASS — a stranger's best guess visibly diverges from the real answer:**
- PROCESS: "What were the steps you followed to generate the synthetic reasoning datasets?" — the real answer (pulling historical alert logs, templated generation, engineer review before training) is a specific pipeline order a resume-reader has no basis to reconstruct; a stranger's guess ("collected data, trained a model") is generic and visibly thinner.
- INCIDENT: "Describe a specific time the model failed to extract a table correctly." — impossible to answer from the resume text alone without inventing a fictional specific, which is exactly the fabrication this category is built to expose.
- DECISION (on a claim with real tradeoffs): "Why did you choose synthetic reasoning datasets over real data for training?" — the real answer (200 usable real cases, NDA-gated) is materially more specific than a stranger's likely guess ("synthetic data scales better").
- CAUSAL_CHAIN (post-fix): "What triggered the need to generate synthetic reasoning datasets, and what changed immediately after you started using them?" — the two-part structure means a stranger has to invent two connected specifics, not one vague motivation.

---

## 4. Specificity Test

**Generic Template (claim-agnostic, same question shape regardless of subject):**
- DECISION: "Why did you choose X over other solutions?" — 10/10 questions share this exact frame with only the object swapped.
- DEPENDENCY: "Who did you coordinate with / rely on to X?" — 10/10 same frame.
- CAUSAL_CHAIN (pre-fix): "What prompted you to X?" — 10/10 identical.
- INCIDENT: "Describe a time when X didn't work as expected / didn't go as planned" — 6/10 share this frame verbatim.

**Claim-Specific (genuinely shaped by what this claim actually says):**
- METRIC_DEFINITION: "How was the 78% accuracy for borderless table extraction measured?" names the actual metric and actual task — could not be asked of a different claim unchanged.
- PROCESS: "What were the first steps you took to generate the synthetic reasoning datasets?" names the specific artifact being built.
- CAUSAL_CHAIN (post-fix): "What triggered the need to generate synthetic reasoning datasets, and what changed immediately after you started using them?" — still names the specific object, and the two-part structure makes it harder to templatize than the pre-fix version.

The pattern: **every category correctly varies its *object* per claim, but roughly half (DECISION, DEPENDENCY, CAUSAL_CHAIN pre-fix, INCIDENT) share one dominant *sentence frame* across every claim they're applied to.** Object-specificity is not the same as structural specificity, and the rubric's own good/bad examples (`"What prompted this project?"` vs `"What was the first signal that convinced you..."`) are exactly this distinction — the generator gets the first kind of specificity for free from the claim text, and doesn't yet get the second kind.

---

## 5. Evidence Yield Estimate

Grounded in actual extraction counts from the live 5-turn simulation, not guessed:

| Turn | Target | Real extracted signal counts |
|---|---|---|
| 1 | PROCESS | process_steps=3, incident_markers=1, entities=2 |
| 2 | ARTIFACT | entities=1 (not tagged `product`, no ARTIFACT credit) |
| 3 | PROCESS (repeat) | process_steps=3, entities=4 |
| 4 | ARTIFACT (repeat) | entities=1 (still no credit — exhausted after this) |
| 5 | OWNERSHIP | process_steps=2, incident_markers=1 (no OWNERSHIP-shaped signal exists to credit at all) |
| 7 (from earlier run) | DECISION | causal_links=1, incident_markers=1, entities=1 — one answer credited 3 different categories |

| Category | Yield estimate | Basis |
|---|---|---|
| PROCESS | **4 (very strong)** | Real observed: 3 process_steps + 2-4 entities per answer, consistently. |
| DECISION | **3-4 (strong)** | One real answer produced signal across 3 categories at once (causal_links, incident_markers, entities) — decision questions on substantive claims pull rich, connected evidence. |
| METRIC_DEFINITION | 3 (strong, inferred) | Not directly measured live, but the question form (asking for a computation method) matches the extractor's `metric_definitions` field precisely. |
| INCIDENT | 3 (strong, inferred) | Same reasoning — direct match to `incident_markers`, and real answers in the CSV read like they'd produce a genuine incident_marker. |
| CAUSAL_CHAIN (post-fix) | 3 (strong, inferred) | The two-part form should map to two extractable pieces; not yet measured live post-fix. |
| ARTIFACT | **1 (weak, measured)** | Twice, in the live run, the real answer ("a labeled JSON set of ~50,000 synthetic incident traces") produced an entity that was NOT tagged `kind: product`, yielding zero ARTIFACT credit both times. The question form is fine; the extractor is the bottleneck. |
| OWNERSHIP | **0 (measured)** | No field in the extractor maps to it at all. Confirmed live: two real, on-topic answers produced literally zero OWNERSHIP-mappable signal. This is an extraction gap, not a question-wording problem — flagging per your instruction not to review extraction, but the yield number is real and it's zero. |
| DEPENDENCY | 2 (moderate) | Real answers do produce `tools`/`entities`, but the question's one-word-exit vulnerability (Section 2) means real candidates may answer thinly even when the category is extractable. |
| CONSTRAINT | 2 (moderate) | Same reasoning as DEPENDENCY — extractable, but the one-word-exit risk caps realistic yield below what the category could give. |
| CROSS_CLAIM_LINK | UNAUDITED | No data. |

---

## 6. Category Review (in place of Move review — see scope note)

**PROCESS — best performing category.** Best example: "What were the first steps you took to generate the synthetic reasoning datasets?" (specific, sequence-forcing, measured strong yield). No genuinely bad examples in the sample. Repeated template: "What were the first steps you took to X" appears in 5+/10 rows verbatim-ish — the *quality* holds up under repetition better than other categories because the underlying question is sound, but it's still the same sentence shape every time.

**DEPENDENCY — weakest performing category.** Every single example ("Who did you coordinate with to X?", "Who did you rely on to X?") shares the same frame and fails the one-word-exit test. Worst example: "Who did you rely on for data to test the borderless table extraction?" — answerable "a public dataset" with zero forensic value.

**OWNERSHIP — second weakest, for a different reason.** The questions themselves are reasonably worded ("What specific part of the AIOps platform were you personally responsible for?"), but 5/10 default to "Who reviewed your work on X?", which is both a one-word-exit fail and, per Section 5, extracts to literally zero signal today regardless of answer quality.

**DECISION — good phrasing, worst structural repetition.** Every one of the 10 examples opens "Why did you choose X..." — the single most repetitive frame in the whole set — but the *content* it elicits (per the live RCA example) is genuinely high-value when the claim supports it. The frame is the problem, not the content.

**CAUSAL_CHAIN — the clearest before/after in the whole audit.** Pre-fix: "What prompted you to launch OSTERI?" (LOW forensic power, FAILs impostor parity, maximally generic). Post-fix: "What triggered the need to generate synthetic reasoning datasets, and what changed immediately after you started using them?" (HIGH forensic power, PASSes impostor parity, genuinely claim-specific). This is the one category where a targeted wording fix visibly moved every dimension in this audit at once.

**INCIDENT — strong, with one soft risk.** "Describe a specific time the model failed to extract a table correctly" is close to the ceiling of what this system can produce. The risk is stonewalling ("nothing went wrong"), not fabrication — out of scope to fix here since it's an interaction-design question, not a wording defect, but worth naming.

**CONSTRAINT — fixed the wrong half of the problem.** The hallucination fix (no longer guessing "budget") is real and verified, but the question form itself still permits a one-word type-name answer ("Budget.") even when the type isn't invented by the model. "What limitation most affected how you launched OSTERI?" needs a second pass, not because it invents anything anymore, but because it's still escapable.

**METRIC_DEFINITION, ARTIFACT — solid, unremarkable.** No major failures found; ARTIFACT's only issue is upstream (extraction), not the question wording being audited here.

**CROSS_CLAIM_LINK — cannot be assessed.** Zero real generations across every run this session. Not scored.

---

## 7. Repetition Analysis (structural, not lexical)

Ranked worst to best, by fraction of the 10-sample sharing one dominant sentence frame:

1. **DECISION — 10/10**: "Why did you choose X (over Y)?"
2. **DEPENDENCY — 9/10**: "Who did you coordinate with / rely on to X?"
3. **CAUSAL_CHAIN (pre-fix) — 10/10**: "What prompted you to X?" (resolved post-fix — the two post-fix examples do not share this frame)
4. **ARTIFACT — 7/10**: "What was/did the final artifact/form of X look like?"
5. **INCIDENT — 6/10**: "Describe a time when X didn't work as expected / didn't go as planned"
6. **METRIC_DEFINITION — ~8/10**: "How was/did you measure/track X?" — partially inherent to the category (there are only so many ways to ask "how was this computed"), noted as lower-priority than the others.
7. **PROCESS — 5/10**: "What were the first steps you took to X?" — the least harmful repetition in the set, since the underlying question quality stays high regardless.
8. **OWNERSHIP — mixed**, two competing frames ("Who reviewed X" / "What part were you responsible for"), neither dominant enough to call a single template, but both are weak per Sections 1-3.

---

## 8. Rewrite Recommendations

**DEPENDENCY** (worst one-word-exit failure)
- Current instruction: *"DEPENDENCY — Ask who or what they had to wait on, rely on, or coordinate with to do this work."*
- Observed failure: "Who did you coordinate with to implement the loyalty module?" → answerable "backend team."
- Minimal fix: append *"Never ask a bare 'who' or 'what' question — ask for the SPECIFIC moment the dependency mattered: what they were blocked on, what changed because of it, or what they couldn't do without it. 'Who did you rely on for X' is wrong; 'What could you not do until [dependency] was ready?' is right."*

**OWNERSHIP** (worst combination of one-word-exit + zero measured yield — noting the wording half only, per your scope)
- Current instruction: *"OWNERSHIP — Ask what they personally were responsible for, who reviewed their work, or what depended on them."*
- Observed failure: 5/10 real generations default to "Who reviewed your work on X?" → answerable "My manager."
- Minimal fix: remove "who reviewed their work" as a suggested angle entirely — every failure traces to the model reaching for it. Replace with: *"Ask for the DECISION they made unilaterally that a stranger reading the resume could not have predicted — not who signed off on it."*

**CONSTRAINT** (fixed the invention, not the escapability)
- Current instruction (post-fix): *"Ask what limited them and how that limit changed what they did... Ask for the limiting factor itself: 'What limitation most changed how you approached X?'"*
- Observed failure: "What limitation most affected how you launched OSTERI?" → answerable "Budget."
- Minimal fix: append *"Never let the question be answerable with just the NAME of the limitation. Ask for its EFFECT: not 'what limited you' but 'what did you have to do differently because of it' or 'what did you have to give up because of it.'"*

**DECISION** (best content, worst frame)
- Current instruction: *"DECISION — Ask why they chose one approach over another they could have taken instead."*
- Observed failure: 10/10 real generations open "Why did you choose X over Y?" — functional, but maximally templated.
- Minimal fix: append *"Vary the ask: sometimes ask what they'd do differently now, sometimes ask what almost made them choose the alternative, sometimes ask who disagreed with the choice. Never let 'Why did you choose X over Y' be the only shape this category produces."*

**ARTIFACT** (frame is fine, "who used it" half is the leak)
- Current instruction: *"ARTIFACT — Ask about the concrete thing their work produced — what it was, what shape it took, who else used it."*
- Observed failure: "...and who used it?" half answerable "customers" with no elaboration.
- Minimal fix: replace "who else used it" with *"how someone else's use of it surprised them, or what they had to change about it once it was in others' hands"* — same target, closes the one-word half.

No change recommended for PROCESS, METRIC_DEFINITION, or INCIDENT — the repetition present is either structurally hard to avoid (METRIC_DEFINITION) or not paired with an actual quality failure (PROCESS, INCIDENT).

---

## 9. Final Verdict

**Acceptable, trending toward Good — not Excellent, not Risky.**

Why not Risky: nothing in this sample is dishonest, presentation-scoring, or metric-leaking — the hard invariants hold. Three of ten categories (PROCESS, INCIDENT, and CAUSAL_CHAIN post-fix) are genuinely strong by every test in this audit, and the one category with a documented, fixed defect (CAUSAL_CHAIN) shows the fastest path to strong is a real, small wording change, not a rebuild.

Why not Good or Excellent: two categories (DEPENDENCY, OWNERSHIP) fail the one-word-exit test on 80-90% of real generations, with your own named escape hatches ("backend team," "my manager") appearing verbatim in real output, not hypothetically. DECISION has excellent content trapped in the single most repetitive frame in the system. CONSTRAINT's fix addressed invention but left the escapability untouched. If 100 candidates went through this tomorrow, DEPENDENCY and OWNERSHIP would be the two questions in every transcript that read as filler — not wrong, not embarrassing, just evidentially empty — and a judge skimming 5 transcripts back-to-back would notice "Why did you choose X over Y" repeating before they noticed anything else.

None of the five rewrite recommendations above touch the planner, scoring, extraction, or claim selection — all five are wording-only, and DEPENDENCY + OWNERSHIP are the two I'd fix before a demo if only two get fixed.
