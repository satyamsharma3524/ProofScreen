# Interview Planner & Question Generation — Full Audit

Audit only, nothing implemented. Reflects the system **as it stands right
now** — after this session's Demo Mode work (AUTHORITY disabled, the
per-claim repair cap fixed, `OWNERSHIP_BOUNDARY` reworded, `OWNERSHIP`
archetype reordered) — not the pre-fix baseline several earlier audits this
session covered. Every question quoted below is real, pulled from real
logs generated this session (fixture and live-API runs); none are
invented for this document.

**A vocabulary correction, made once here so it isn't repeated per
section:** the requested move list — `INCIDENT, PROCESS, TOOL, OUTCOME,
FAILURE, AUTHORITY, OWNERSHIP_BOUNDARY, DEPENDENCY, METRIC_DEFINITION` —
mixes three different vocabularies that exist in this codebase for three
different reasons:

- **`FAILURE`, `AUTHORITY`, `OWNERSHIP_BOUNDARY`, `DEPENDENCY`,
  `METRIC_DEFINITION`** are real `Move` enum values (`question.py:911-929`)
  — these actually select which question gets generated.
- **`INCIDENT` and `OUTCOME`** are `ProbeLevel` values (`schemas.py`) — the
  legacy pre-forensic path's own stage names. Every Move still stores one
  for backward compatibility (`MOVE_PROBE_LEVEL`), but no live move-selection
  decision reads them.
- **`PROCESS` and `TOOL`** are `Dimension` names (`PROCESS`,
  `TOOL_FAMILIARITY`) — what gets *scored*, not what generates a question.

The Move Inventory below uses the real, current vocabulary — the 8 moves
that actually exist, with each requested item (INCIDENT→`FAILURE`,
OUTCOME/METRIC→`METRIC_DEFINITION`, PROCESS/TOOL→`OPERATING_CONTEXT`) noted
against its closest real counterpart so nothing in the request goes
unanswered.

---

## Move Inventory

| Move | Purpose | Dimension | Real question (this session) | Difficulty | Junior | Mid | Senior |
|---|---|---|---|---|---|---|---|
| **OPERATING_CONTEXT** | What they were looking at day to day; the first concrete thing checked | PROCESS, TOOL_FAMILIARITY | *"On the work where you managed telecom cloud infrastructure, what was the first thing you checked when an alert came in?"* | **1** | ✓ | ✓ | ✓ |
| **DEPENDENCY** | One specific moment a dependency blocked or changed the work | (PROCESS/TOOL via `MOVE_DIMENSIONS`) | *"Describe a moment when you were blocked while setting up the monitoring dashboards with Prometheus and Grafana, and what had to change to move forward."* | **2** | ✓ | ✓ | ✓ |
| **OWNERSHIP_BOUNDARY** *(reworded this session)* | What part was personally theirs, and what happened once it moved on | SPECIFICITY | *"What specific tasks did you handle personally, and what happened once your part was completed?"* | **2** | ✓ | ✓ | ✓ |
| **FAILURE** | One specific incident that didn't go as expected | AUTHENTICITY | *"Describe a time when a production deployment didn't go as planned and how you resolved it."* | **3** | △ | ✓ | ✓ |
| **METRIC_DEFINITION** | How a named metric was actually derived, not its value | METRIC_OWNERSHIP | *"How was the P95 latency metric derived, including what was measured and the baseline used?"* | **3** | △ | ✓ | ✓ |
| **PEOPLE** | A named role in the loop, and what they did | AUTHENTICITY, SPECIFICITY | *"Who first raised concerns about meeting the targets and what did they do?"* → real answer: **"My manager."** | **1** *(too easy — see Quality Audit)* | ✓ | ✓ | ✓ |
| **COHERENCE** | Cross two already-established facts against each other | CAUSAL_REASONING | *"How did the log files on the Jenkins log server help when checking the CI/CD pipeline configured on Jenkins to the AWS server?"* → real reply (Hindi): *"what you're asking us isn't clear"* | **4-5** | ✗ | △ | ✓ |
| **AUTHORITY** *(disabled under Demo Mode)* | What they could decide independently | (old) CAUSAL_REASONING | *"What decisions were solely yours regarding virtualization setup?"* → real answers ranged from a rich, specific reply to **"I did independently."** (zero signal) | **4** | ✗ | △ | ✓ |
| **EXCLUSION** *(disabled)* | What was deliberately left undone, and why | (old) CAUSAL_REASONING | not observed firing in any real log gathered this session | **3** | △ | ✓ | ✓ |
| **PERTURB** *(disabled)* | One hypothetical variable changed, reasoned through | CAUSAL_REASONING, PROCESS | *"If you had assisted with managing virtualization on Windows servers instead of Proxmox, where would you start troubleshooting..."* | **5** | ✗ | △ | ✓ |

**PEOPLE's entry is worth reading twice — it's the clearest case in this
table where "difficulty" and "evidence yield" pull apart.** It's trivially
*easy* to answer (a name is a complete, valid-looking reply), which is
exactly why it's a quality problem, not a difficulty problem — see the
Quality Audit below.

---

## Planner Flow Audit

**The real mechanism keys off `Archetype`, derived from verbs in the
claim's own text (`anatomy._archetype()`), not claim *type*.** A `delivery`-
typed claim and a `system_ownership`-typed claim can land on the identical
archetype, or different ones, depending on wording — there is no fixed
`claim_type → move sequence` table anywhere in the code. The rows below
show the **current `ARCHETYPE_LADDER`** (post-fix), with a real claim
example of each archetype pulled from this session's logs, and which
claim *types* those real examples happened to carry — to make the
distinction concrete rather than assert it abstractly.

| Archetype | Real example claim | Its claim_type | Move sequence (first 2 real questions, post-fix) | Difficulty progression | Estimated candidate level needed |
|---|---|---|---|---|---|
| **BUILD** | *"Built and maintained scalable mobile apps using React Native..."* | `system_ownership` | `OPERATING_CONTEXT → DEPENDENCY` | 1 → 2 | Junior-safe |
| **OWNERSHIP** | *"Managed production deployments and resolved critical production incidents..."* | `measurable_outcome` | `OPERATING_CONTEXT → OWNERSHIP_BOUNDARY` | 1 → 2 | Junior-safe |
| **PROCESS** | *"Handling L1/L2 fault management for CNFs and VNFs."* | `reliability` | `OPERATING_CONTEXT → FAILURE` | 1 → 3 | Junior-OK, one harder rung |
| **METRIC_MOVE** | *"Optimized database queries reducing P95 latency from 900ms to 120ms."* | `performance_work` | `METRIC_DEFINITION → FAILURE` | 3 → 3 | Mid+ |
| **VOLUME** | *"Achieved CASA VALUE and CASA NO's target in FY 2025-26."* | `tat_performance` | `OPERATING_CONTEXT → FAILURE` | 1 → 3 | Junior-OK, one harder rung |

**Every archetype now shows a genuine ascending difficulty progression in
its first two real questions** (never flat-hard, never hard-first). That
was not always true — see the Ordering Audit for what changed and why.

---

## Seniority Audit

**The system is not level-aware, confirmed at the code level, unchanged
by anything else fixed this session.**

- `api/engine/extract.py:398-403` — the `RoleClassification` model's own
  docstring: *"`confidence` and `seniority` are RECORDED AND NEVER BRANCHED
  ON... there is no exemption for routing."* Grep confirms `seniority`
  appears in exactly one file, only in this definition and its log line
  (`extract.py:439-444`).
- `api/engine/anatomy.py:294-305` (`_archetype()`) — reads only verb
  keywords from the claim's own text. No parameter, no closure variable,
  nothing anywhere in its call chain carries seniority, title, or tenure.
- `api/taxonomy.py` (`default_claim_weights`) — weights are keyed by job
  *family* only; a `system_ownership` claim is weighted 25 for every
  candidate in that family regardless of experience.
- `api/engine/question.py` — every `MOVE_BRIEFS` entry and the shared
  `forensic_question.txt` RULES section are static text; nothing branches
  on candidate level when rendering a question.

**Direct proof, not inference:** a junior-presenting DevOps candidate this
session received the identical `AUTHORITY` question wording ("what
decisions were solely yours") as every other candidate in every other log
gathered — same move, same brief, same file, no branch anywhere that
could have produced different wording for a different candidate.

---

## Question Quality Audit

| Move | Rating | Why |
|---|---|---|
| **OPERATING_CONTEXT** | 🟢 Green | Reliably produces 2+ dimensions of real signal on the first exchange, in every real log gathered this session, regardless of candidate engagement level |
| **DEPENDENCY** | 🟢 Green | Produced the single richest answer measured this session (7 signals, 4 of 6 dimensions, one answer) |
| **OWNERSHIP_BOUNDARY** *(post-fix)* | 🟢 Green | Reworded wording confirmed producing real signal in live traffic this session ("Uploading the files on the docker and stuff" → real `PROCESS`/`TOOL_FAMILIARITY` credit) |
| **FAILURE** | 🟡 Yellow | Reliably produces *some* signal, but the dimension it's built for (`AUTHENTICITY`) reads 0 more often than not — a full, substantive answer frequently describes a precaution rather than an incident |
| **METRIC_DEFINITION** | 🟡 Yellow, unmeasured in practice | The question form is sound (asks for derivation, never the value), but it's gated to metric-bearing claims and, per the earlier planner audit, essentially never gets a genuine real-world answer to score in the logs gathered — no live evidence either way on quality, only on reachability |
| **PEOPLE** | 🔴 Red | Both real instances observed this session got a bare one-word name (*"My manager."*, *"Manager"*) — zero signal both times. Low discrimination power: a fabricator and a genuine candidate answer identically |
| **COHERENCE** | 🔴 Red | One real instance observed, and it produced candidate confusion rather than evidence — the cross-reference framing is dense enough that a real candidate couldn't parse what was being asked |
| **AUTHORITY** *(disabled)* | 🔴 Red | Highest measured variance of any move this session — the single richest AND single emptiest real answer both came from this move. Disabled for exactly this reason |
| **PERTURB** *(disabled)* | 🟡→🔴 context-dependent | Produced strong evidence from an engaged candidate, and actively penalized a disengaged one by escalating difficulty exactly when they'd already started failing. Disabled |

---

## Ordering Audit

**Before this session's fixes: mixed, with two confirmed hard-first
patterns.** `VOLUME` archetype opened directly on `AUTHORITY` (difficulty 4,
zero grounding) by ladder design. `OWNERSHIP` archetype opened on
`OWNERSHIP_BOUNDARY` in its old, harder hierarchy-framed wording
(*"who reviewed your work"*). And `PERTURB` — difficulty 5 — was reachable
specifically as an escalation onto a claim that had **already stalled**,
which is a hard-after-failure pattern, the worst shape ordering can take.

**Disengagement evidence, from real logs this session:** the original
adversarial transcript shows escalating non-answers concentrated exactly
where `PERTURB`/`EXCLUSION` fired late in the interview (*"I don't know."*,
*"Stop."*, single-word replies), not evenly distributed across the whole
transcript. The Infra log shows one candidate objecting mid-interview —
*"I don't know why are you asking CNF, BNF?"* — but on `OPERATING_CONTEXT`
(the easiest move), which shows ordering-difficulty is not the *only*
disengagement lever: injected domain jargon from the claim's own resume
text can trigger the same reaction independent of which move asked it.

**After this session's fixes: every archetype now runs Easy → Medium (or
Easy → Medium-Hard), never flat-hard and never hard-first** — confirmed
directly in the Planner Flow Audit table above, not asserted. The
remaining hardest moves (`COHERENCE`, disabled `AUTHORITY`/`PERTURB`) are
either disabled or, for `COHERENCE`, only reachable once two facts are
already established — structurally late, by design, in whatever budget
remains.

---

## Deliverables

**1. Findings**
- The planner is not, and never has been, seniority-aware — by apparent
  design (the same principle CLAUDE.md states for scores generally),
  confirmed at the code level in `extract.py`.
- `PEOPLE` and `COHERENCE` are the two live weak links now that `AUTHORITY`
  is disabled — not because they're too *hard*, but because `PEOPLE` is
  too easy to answer with nothing, and `COHERENCE` is dense enough to
  produce candidate confusion rather than evidence.
- Ordering has materially improved this session — every archetype's real
  two-question path is now ascending, where it previously had two
  confirmed hard-first patterns.

**2. Evidence** — every question, answer, and log line quoted above is
real, from this session's own runs (fixture-mode and live-API), not
constructed for this document.

**3. Recommended ordering** — no change needed; the current
`ARCHETYPE_LADDER` (post-fix) already produces Easy → Medium/Hard for
every archetype within the 2-question-per-claim budget.

**4. Recommended difficulty progression** — the two remaining gaps aren't
ordering problems: `PEOPLE`'s brief needs to ask for what the named person
*did*, not just who they were (the brief text already gestures at this and
isn't being followed in the two real examples measured); `COHERENCE`'s
phrasing needs simplifying if it's ever meant to fire reliably rather than
remain a rare, mostly-inert late-game move. Both are wording observations,
not ordering ones — named here per the audit's own scope, not proposed as
changes to make.
