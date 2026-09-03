# ProofScreen — documentation index

Two developers share this repo and push to `main` hourly. These documents are
what keep that conflict-free, so the reading order below is not a suggestion:
`EXECUTION_STANDARD.md` §1 requires the frozen documents to be read *before*
proposing code, and `DEVELOPER_B_CONTRACT.md` declares itself subordinate to
three of them.

`CLAUDE.md` and `README.md` stay at the repo root. Everything else is here.

---

## Read in this order

| # | Document | Why it is first |
|---|---|---|
| 1 | [EXECUTION_STANDARD.md](EXECUTION_STANDARD.md) | The binding process: architecture is sacred, plan before code, tests define acceptance. Every other document is subordinate to it |
| 2 | [ARCHITECTURE_LOCK_v1.md](ARCHITECTURE_LOCK_v1.md) | What is frozen, and the logged deviations from it |
| 3 | [EVALUATION_ARCHITECTURE_PRINCIPLES.md](EVALUATION_ARCHITECTURE_PRINCIPLES.md) | Why the model never scores, and what "evidence" means here |
| 4 | [PROOFSCREEN_DOMAIN_MODEL.md](PROOFSCREEN_DOMAIN_MODEL.md) | The vocabulary — claim, probe, signal, dimension, evidence |
| 5 | [PHASE_1_EXECUTION_PLAN.md](PHASE_1_EXECUTION_PLAN.md) | The active phase |
| 6 | [PHASE_1_TASKS.md](PHASE_1_TASKS.md) | P1-00 … P1-13: files, tests, migration, binary acceptance, dependency graph |
| 7 | [PHASE_1_SUCCESS_METRICS.md](PHASE_1_SUCCESS_METRICS.md) | M1–M5, guardrails, counter-metrics. All computable from stored data |

Then whichever of the two contracts applies to you:

- **Developer B** — [DEVELOPER_B_CONTRACT.md](DEVELOPER_B_CONTRACT.md).
  Ownership, task order, branch names, and a precondition to verify *before
  branching*.
- **Developer A** — ownership table in [../README.md](../README.md), overridden
  for Phase 1 by the do-not-edit list in `DEVELOPER_B_CONTRACT.md`. See the
  ownership note below.

---

## Reference — read when the topic comes up

| Document | Read it when |
|---|---|
| [TRANSFER_DESIGN_AUDIT.md](TRANSFER_DESIGN_AUDIT.md) | Touching the TRANSFER probe. §3 is the family-invariance guarantee, §5 the brittleness table. Cited directly from `engine/signals.py` and `engine/question.py` |
| [FAMILY_TAXONOMY_REVIEW.md](FAMILY_TAXONOMY_REVIEW.md) | Touching `taxonomy.py`, `detect_family`, or `data/claim_taxonomy.json` |
| [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) | Before deploying anything |
| [REPO_STRUCTURE.md](REPO_STRUCTURE.md) | Orienting in the tree; the data-flow one-liners |
| [PLATFORM_ARCHITECTURE_REVIEW.md](PLATFORM_ARCHITECTURE_REVIEW.md) | Scaling questions — cohorts, families, multi-tenant |
| [PHASE_2_EXECUTION_PLAN.md](PHASE_2_EXECUTION_PLAN.md) | **Not yet.** Phase 2 work is forbidden until Phase 1 exits |

## Superseded — history, not instructions

Kept because the reasoning is worth having, but **do not take direction from
them**; where they disagree with the numbered list above, the numbered list
wins.

| Document | Superseded by |
|---|---|
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | `PHASE_1_TASKS.md` |
| [EXECUTION_PLAN.md](EXECUTION_PLAN.md) | `PHASE_1_EXECUTION_PLAN.md` |
| [SHIP_PLAN.md](SHIP_PLAN.md) | `PHASE_1_EXECUTION_PLAN.md` |
| [PLAN_REVIEW.md](PLAN_REVIEW.md) | Critique of the above; its conclusions are folded into the standard |
| [ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md) | `ARCHITECTURE_LOCK_v1.md` |

---

## Two things a new session gets wrong

**Ownership has two sources and they disagree.** The table in `../README.md`
assigns `engine/signals.py` to Developer B. The do-not-edit list in
`DEVELOPER_B_CONTRACT.md` assigns it to A. For Phase 1 the contract wins, and
`PHASE_1_TASKS.md` P1-03 says why: *"Owner A, **B reviews the `signals.py`
hunk**"* — A edits, B reviews. Do not re-litigate this per task.

**The planning-to-code ratio is a known risk, already logged.** 19 documents
sit in this folder. `EXECUTION_STANDARD.md` proposes C2 as the guardrail — *no
phase may add more planning documents than it merges implementation tasks* —
and notes Phase 1's documentation budget is already spent. Adding another
document here is a decision, not a default. Prefer editing one of these.
