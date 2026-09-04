"""Makes `scripts` importable.

The only reason this file exists: `PHASE_1_TASKS.md` P1-12 requires that the
validation endpoint and the validation script return *identical* numbers —
"one implementation, two surfaces". The plan puts the implementation in
`scripts/validation_report.py`, so `api/routers/recruiter.py` has to import it.

The alternative was re-implementing the maths in the router, which guarantees
the two surfaces drift apart and makes P1-12's acceptance criterion
unverifiable by construction.
"""
