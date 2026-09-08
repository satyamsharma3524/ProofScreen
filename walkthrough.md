# Walkthrough: Pre-Hackathon ProofScreen Fixes & Recruiter Alignment Pass

We have successfully implemented and verified all pre-hackathon fixes and recruiter-alignment improvements for ProofScreen without altering core architecture, schema (`api/schemas.py` remains 100% frozen), or recruiter role weighting logic. All **518 unit & integration tests** pass cleanly.

---

## 1. Fix Summary

### FIX 1 — OPERATIONAL EVIDENCE BONUS & OWNERSHIP FALSE NEGATIVE REDUCTION
- **Files Modified**: [api/engine/scoring.py](file:///Users/212705/ProofScreen/api/engine/scoring.py#L120-L185), [api/engine/signals.py](file:///Users/212705/ProofScreen/api/engine/signals.py#L272-L285, #L436-L471)
- **Change**: 
  - Added claim-level evidence bonus multipliers for `incident_markers` (+0.10), complete `causal_links` (+0.10), and `constraints` (+0.05).
  - Inferred ownership evidence from first-person operational action verbs (`_is_first_person_action()` checking `"I isolated"`, `"I handled"`, `"I led"`, `"I deployed"`, `"I configured"`, `"I fixed"`), opening the Ownership gate while keeping explicit `boundaries` as highest evidence.

### FIX 2 — DECISION QUALITY IMPROVEMENT & TROUBLESHOOTING STEP DETECTION
- **Files Modified**: [api/engine/signals.py](file:///Users/212705/ProofScreen/api/engine/signals.py#L286-L296, #L350-L375, #L400-L434), [api/engine/orchestrator.py](file:///Users/212705/ProofScreen/api/engine/orchestrator.py#L380-L392), [api/engine/question.py](file:///Users/212705/ProofScreen/api/engine/question.py#L1197-L1220)
- **Change**: 
  - Differentiated strong trade-off decisions (`_is_strong_decision()` checking `"evaluated"`, `"compared"`, `"versus"`, `"tradeoff"`, `"instead of"`, `"alternative"`) at 1.0 weight from simple choices at 0.5 weight in `score_judgment()`.
  - Added `_is_troubleshooting_step(step)` detecting operational keywords (`fix`, `debug`, `investigate`, `diagnose`, `isolated`, `resolved`, `mitigated`, `restored`, `recovered`, `rollback`, `root cause`, `outage`, `incident`, `failure`, `crash`, `degraded`, `leak`, `corruption`, `deadlock`, `timeout`, `exhaustion`). Weighted at 1.5x in `score_execution()` with basis annotation `• Operational troubleshooting step: <step>`.

### FIX 3 — QUANTITY EXTRACTION & STRONG CLAIM PRIORITIZATION
- **Files Modified**: [api/engine/evidence.py](file:///Users/212705/ProofScreen/api/engine/evidence.py#L122-L130, #L187-L200), [api/engine/signals.py](file:///Users/212705/ProofScreen/api/engine/signals.py#L380-L415), [api/engine/extract.py](file:///Users/212705/ProofScreen/api/engine/extract.py#L220-L225, #L707-L745), [api/engine/orchestrator.py](file:///Users/212705/ProofScreen/api/engine/orchestrator.py#L650-L655)
- **Change**: 
  - Added regex patterns `_SPELLED_QTY` and `_RELATIVE_QTY` in `heuristic_signals()` and updated LLM prompts to extract spelled-out counts ("three engineers", "two quarters", "a dozen endpoints") and relative/multiplicative quantities ("cut latency in half", "doubled throughput").
  - Implemented `claim_strength_bonus(text, metric)` boosting claims containing incident markers (+3.0), causal/outcome language (+2.0), quantities/metrics (+2.0), constraints (+1.5), and ownership verbs (+1.5). Sorted/ranked claim inventory in `extract.py` and `build_claim_states()` in `orchestrator.py` so strongest operational claims are interviewed first.

### FIX 4 — BETTER CAUSAL CHAIN RECALL
- **Files Modified**: [api/engine/evidence.py](file:///Users/212705/ProofScreen/api/engine/evidence.py#L131-L150, #L258-L295), [api/prompts/v2_extract_signals.txt](file:///Users/212705/ProofScreen/api/prompts/v2_extract_signals.txt#L33-L36), [api/prompts/extract_signals.txt](file:///Users/212705/ProofScreen/api/prompts/extract_signals.txt#L33-L36)
- **Change**: Added multi-sentence sliding window scan (window sizes 4, 3, 2) in `heuristic_signals()` to extract complete `CausalLink` chains when cause, action, and outcome span adjacent sentences.

### FIX 5 — TEXTBOOK ANSWER DETECTION SIGNAL
- **Files Modified**: [api/engine/signals.py](file:///Users/212705/ProofScreen/api/engine/signals.py#L297-L308, #L326-L338)
- **Change**: Added `_is_theoretical_only()` check that annotates Knowledge basis with `• Answer style: Primarily theoretical (no operational incidents or causal chains)` when concept/metric explanations are present without operational evidence. No score penalties; metadata only.

### FIX 6 — RECRUITER EXPLANATION IMPROVEMENT
- **Files Modified**: [api/engine/signals.py](file:///Users/212705/ProofScreen/api/engine/signals.py#L325-L505)
- **Change**: Transformed raw count basis outputs (e.g. "3 process steps, 2 tools") into descriptive action summaries (e.g. `• Executed step: Configured connection pool`, `• Evaluated decision tradeoff: Selected Postgres over MySQL`).

### CONVERSATIONAL FALLBACK & SKIP BEHAVIOR
- **Files Modified**: [api/engine/evidence.py](file:///Users/212705/ProofScreen/api/engine/evidence.py#L55-L95), [api/engine/orchestrator.py](file:///Users/212705/ProofScreen/api/engine/orchestrator.py#L240-L245), [api/engine/question.py](file:///Users/212705/ProofScreen/api/engine/question.py#L700-L755)
- **Change**: Added `is_memory_exhausted_or_skip()` detection for candidate memory exhaustion/skips ("I don't know", "Not sure", "Skip", etc.), bypassing repair turns and formatting warm human transition acknowledgements while stripping robotic phrases.

---

## 2. Before / After Examples

| Dimension / Fix | Before Implementation | After Implementation |
| --- | --- | --- |
| **Fix 1 (Ownership)** | "I isolated the endpoint and killed 120 idle queries" capped at 40 on Ownership ("no explicit boundary declared"). | Gate opens and Ownership scores 60+, basis: `• Owned operational action: I isolated the leaking endpoint`. |
| **Fix 2 (Decision Quality & Troubleshooting)** | Simple choice scored same weight as trade-off. "built docker image" scored same as "recovered corrupted DB". | Simple choice receives 0.5 weight, strong trade-off 1.0. Troubleshooting step receives 1.5x weight (`• Operational troubleshooting step`). |
| **Fix 3 (Quantity & Claim Prioritization)** | "three engineers" ignored. Generic claims ("worked on backend") interviewed before incident claims. | Spelled-out numbers extracted. Incident claims ("fixed Black Friday outage", "reduced latency by 70%") prioritized first. |
| **Fix 4 (Causal Chain Recall)** | Multi-sentence response ("Queue backed up. Found lag. Increased partitions. Latency normal.") produced zero causal links. | Extracted as complete `CausalLink` (`cause="Queue backed up"`, `action="Increased partitions"`, `outcome="Latency normal"`). |
| **Fix 5 (Textbook Detection)** | Pure textbook answer scored Knowledge with no indication of missing operational context. | Basis explicitly highlights: `• Answer style: Primarily theoretical (no operational incidents or causal chains)`. |
| **Fix 6 (Recruiter Explanations)** | Basis showed cryptic raw counts: `basis="1 process step, 1 tool"`. | Basis shows clear action summary: `• Executed step: Configured connection pool\n• Applied tool in workflow: Postgres`. |

---

## 3. Verification Results

### Automated Test Suite
Run command: `./.venv/bin/pytest -q`

Result: **518 passed in 18.17s**

Key test files verified:
- [tests/test_final_audit_fixes.py](file:///Users/212705/ProofScreen/tests/test_final_audit_fixes.py): **6 passed**
- [tests/test_recruiter_alignment_fixes.py](file:///Users/212705/ProofScreen/tests/test_recruiter_alignment_fixes.py): **3 passed**
- [tests/test_conversational_fallback.py](file:///Users/212705/ProofScreen/tests/test_conversational_fallback.py): **PASSED**
- [tests/test_final_fixes.py](file:///Users/212705/ProofScreen/tests/test_final_fixes.py): **PASSED**
- [tests/test_pipeline.py](file:///Users/212705/ProofScreen/tests/test_pipeline.py): **87 PASSED**

### Seeding & Fixtures
Run command: `./.venv/bin/python seed.py --reset && ./.venv/bin/python scripts/dump_fixture.py`

Result: **Clean seed & fixture generation across all 3 recruiter role lenses.**
