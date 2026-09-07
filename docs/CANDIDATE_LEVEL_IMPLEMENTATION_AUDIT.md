# Candidate-Level Interview Model — Implementation Audit

Implementation of the minimal model proposed in
`docs/CANDIDATE_LEVEL_AUDIT.md` §5 and described in
`docs/QUESTION_EVAL_HARNESS_AND_LEVEL_MODEL.md`. Scope is exactly the five
goals given: persist seniority, gate move selection by it, log the gate,
touch nothing else. The offline evaluation harness those docs also describe
is **not** part of this change — deferred, as instructed, to after this
lands.

Constraints honoured: no new LLM call (goal A reuses `classify_role`'s
existing `seniority` field, previously read and discarded); no change to
extraction *contracts*, scoring, the evidence graph, or competence
calculations; `api/schemas.py` untouched; unknown seniority preserves
exactly today's behaviour.

## 1. Files changed

| File | Change |
|---|---|
| `api/engine/extract.py` | `_normalise_seniority()` (new). `classify_role()` returns `(family, seniority)` instead of `family`. `extract_claims()` returns `(family, claims, seniority)` instead of `(family, claims)`. |
| `api/models.py` | `Candidate.seniority: str \| None` — new column, internal only, not in `api/schemas.py`. |
| `api/db.py` | `_REQUIRED_COLUMNS` gains `("candidates", "seniority")` per CLAUDE.md rule 7 (`create_all()` cannot add a column to an existing table). |
| `api/engine/orchestrator.py` | `create_session()` persists `candidate.seniority`. `ClaimState` gains `candidate_seniority`. `forensic_moves_left()`'s AUTHORITY/EXCLUSION filter is level-aware instead of a blanket demo-mode exclusion. `build_claim_states()` fetches the `Candidate` row once and populates `candidate_seniority` on every claim. `plan_next_forensic`'s PERTURB stall branch (step 4) checks the level gate as an alternative to `settings.transfer_probe`. `brief()` logs the required line. New helper `_level_filtered_moves()`. |
| `api/engine/question.py` | `LEVEL_RESTRICTED` (new) and `level_appropriate()` (new) — the single source of truth for which moves are gated and at which seniority. |
| `tests/test_taxonomy.py`, `tests/test_extract.py`, `tests/test_tenancy.py` | Updated call sites / a mock's expected output for the new return arities and the new `_REQUIRED_COLUMNS` entry. No behavioural assertions changed. |
| `scripts/inspect_resume_pipeline.py` | Unpacks `extract_claims`'s new 3-tuple (diagnostic script, not under `pytest`). |

No change to `api/schemas.py`, `engine/signals.py`, `engine/scoring.py`,
`engine/graph.py`, `engine/evidence.py`, or any prompt template. `pytest -q`:
499/500 passing, the one failure pre-existing and unrelated (`test_provenance.py`
picks up untracked `v2_*`/`claim_graph` prompt files via a directory glob —
present before this change, reproducible on `main` with those files
untracked).

## 2. Exact filtering logic

```python
# api/engine/question.py
LEVEL_RESTRICTED: dict[Move, frozenset[str]] = {
    Move.AUTHORITY: frozenset({"mid", "senior"}),
    Move.EXCLUSION: frozenset({"senior"}),
    Move.PERTURB: frozenset({"senior"}),
}

def level_appropriate(move: Move, seniority: str | None) -> bool:
    allowed = LEVEL_RESTRICTED.get(move)
    if allowed is None:
        return True
    if seniority is None:
        return False
    return seniority in allowed
```

Every other move (`METRIC_DEFINITION`, `OWNERSHIP_BOUNDARY`,
`OPERATING_CONTEXT`, `FAILURE`, `DEPENDENCY`, `PEOPLE`, `COHERENCE`) is absent
from the dict and therefore unrestricted at every seniority, including
unknown — this is what "no other planner behaviour changes" (goal spec,
closing line) requires.

Two call sites apply it, both inside move **selection**, never inside
wording generation (`generate_question` / `MOVE_BRIEFS` are untouched — goal
C):

```python
# ClaimState.forensic_moves_left() — replaces the old blanket
# `settings.demo_mode and mv in (EXCLUSION, AUTHORITY)` exclusion
and not (
    settings.demo_mode
    and mv in (question_engine.Move.EXCLUSION, question_engine.Move.AUTHORITY)
    and not question_engine.level_appropriate(mv, self.candidate_seniority)
)
```

```python
# plan_next_forensic, step 4 (PERTURB stall branch) — replaces the old
# unconditional `if settings.transfer_probe:`
if not (
    settings.transfer_probe
    or (
        settings.demo_mode
        and question_engine.level_appropriate(
            question_engine.Move.PERTURB, state.candidate_seniority
        )
    )
):
    continue
```

Both sites are scoped to stay inside `settings.demo_mode`'s existing
behaviour rather than replacing it: outside demo mode (`demo_mode=False`),
today's behaviour — AUTHORITY/EXCLUSION always available, PERTURB gated only
by `transfer_probe` — is exactly preserved, seniority or not. Inside demo
mode, the gate narrows from "always off" to "off unless the candidate's
level unlocks it," and unknown seniority (`candidate_seniority is None`)
falls through `level_appropriate()`'s `if seniority is None: return False`,
reproducing today's blanket exclusion exactly (constraint 4).

Logging (goal D), added at the one place a move is actually chosen
(`brief()`, called from every branch of `plan_next_forensic`):

```python
level = state.candidate_seniority or "unknown"
log.info(
    "planner level=%s candidate seniority=%s allowed_moves=%s filtered_moves=%s",
    level, level,
    [m.value for m in state.forensic_moves_left()],
    [m.value for m in _level_filtered_moves(state)],
)
```

`_level_filtered_moves()` reports, uniformly across all three gated moves,
whatever is precondition-eligible right now (`move_available()` true, not yet
used) but blocked specifically by the level gate — not moves that are
unavailable for other reasons (already used, no metric, no seam pair).

## 3. Before / after — real runs, not hypotheticals

Captured with `scripts/verify_level_gate.py`-equivalent (constructs real
`ClaimState` objects the same way `tests/test_policy.py::state()` does, then
calls the actual `plan_next_forensic`) — no mocks of the gate itself. Three
claims in every run: a VOLUME claim (opens on AUTHORITY), a BUILD claim
already past its opening move (next move reachable is EXCLUSION), and a
stalled claim (two answers, zero new signal each) to exercise the PERTURB
branch in isolation.

Actual `planner level=...` log lines emitted:

```
planner level=unknown candidate seniority=unknown allowed_moves=['OPERATING_CONTEXT', 'FAILURE', 'PEOPLE', 'PERTURB'] filtered_moves=['AUTHORITY', 'EXCLUSION', 'PERTURB']
planner level=junior  candidate seniority=junior  allowed_moves=['OPERATING_CONTEXT', 'FAILURE', 'PEOPLE', 'PERTURB'] filtered_moves=['AUTHORITY', 'EXCLUSION', 'PERTURB']
planner level=mid     candidate seniority=mid     allowed_moves=['AUTHORITY', 'OPERATING_CONTEXT', 'FAILURE', 'PEOPLE', 'PERTURB'] filtered_moves=['EXCLUSION', 'PERTURB']
planner level=senior  candidate seniority=senior  allowed_moves=['AUTHORITY', 'OPERATING_CONTEXT', 'FAILURE', 'PEOPLE', 'PERTURB'] filtered_moves=[]
```

### VOLUME claim ("Processed 500 refund requests per week..."), opening move

| Seniority | `forensic_moves_left()` | `plan_next_forensic` picks | Note |
|---|---|---|---|
| unknown | OPERATING_CONTEXT, FAILURE, PEOPLE, PERTURB | **PEOPLE** | AUTHORITY absent — identical to pre-change demo behaviour |
| junior | OPERATING_CONTEXT, FAILURE, PEOPLE, PERTURB | **PEOPLE** | same as unknown — junior never unlocks anything |
| mid | **AUTHORITY**, OPERATING_CONTEXT, FAILURE, PEOPLE, PERTURB | **AUTHORITY** | newly unlocked — the claim's own designed opening move |
| senior | **AUTHORITY**, OPERATING_CONTEXT, FAILURE, PEOPLE, PERTURB | **AUTHORITY** | same as mid for this move |

(`plan_next_forensic`'s actual pick differs slightly from raw ladder order
because breadth/seam/depth ordering and session-fresh rotation apply across
all three claims in the run — the table's middle column, taken straight from
`forensic_moves_left()`, is the ground truth for what the gate itself does.)

### BUILD claim ("Migrated the checkout service off the legacy monolith"), already used OPERATING_CONTEXT

| Seniority | `forensic_moves_left()` |
|---|---|
| unknown / junior | DEPENDENCY, FAILURE, PERTURB |
| mid | DEPENDENCY, FAILURE, PERTURB *(EXCLUSION still absent)* |
| senior | DEPENDENCY, FAILURE, **EXCLUSION**, PERTURB |

Confirms the mid-tier spec precisely: mid unlocks AUTHORITY only, not
EXCLUSION.

### Stalled claim, PERTURB branch (step 4) in isolation

| Seniority | `plan_next_forensic` result |
|---|---|
| unknown | `None` — no perturbation offered |
| junior | `None` |
| mid | `None` |
| senior | **PERTURB** |

`level_appropriate()` direct calls, same run:

```
level_appropriate(AUTHORITY, 'unknown') = False   level_appropriate(AUTHORITY, 'junior') = False
level_appropriate(EXCLUSION, 'unknown') = False   level_appropriate(EXCLUSION, 'junior') = False
level_appropriate(PERTURB,   'unknown') = False   level_appropriate(PERTURB,   'junior') = False

level_appropriate(AUTHORITY, 'mid') = True        level_appropriate(AUTHORITY, 'senior') = True
level_appropriate(EXCLUSION, 'mid') = False        level_appropriate(EXCLUSION, 'senior') = True
level_appropriate(PERTURB,   'mid') = False        level_appropriate(PERTURB,   'senior') = True
```

## 4. What this does not change

- `settings.demo_mode=False`: identical to before this change — the level
  gate only narrows demo mode's own existing exclusions, it does not add a
  new restriction outside demo mode.
- Question wording, `MOVE_BRIEFS`, prompt templates, validation rules: none
  touched (goal C).
- Extraction contracts, `api/schemas.py`, scoring, the evidence graph,
  competence calculations: none touched.
- A candidate whose seniority the classifier cannot determine (header too
  thin, classifier off, or an unrecognised free-text value) gets exactly
  today's junior-equivalent behaviour — AUTHORITY, EXCLUSION and PERTURB all
  stay off, matching the pre-change blanket exclusion bit-for-bit.
