"""
D7 — provenance.  NO LLM CALL IN THIS FILE (it reads the wrapper; it never
uses it).

WHAT THIS ANSWERS

    "Why did this candidate score 82 in March and 71 today?"

Not with a label. With components: taxonomy tax_1@4e0f5b, rubric rub_1,
scoring score_1, question policy qpol_2, three prompt hashes, a code version,
the model requested, the mode, and the eight settings that materially change
behaviour. `eval_v3` answers *"was this the same system?"* and not *"what
changed?"* — a recruiter asking about 82 versus 71 needs the diff, which is why
`PRODUCTION_READINESS.md` 1 says store the components and DERIVE the composite.

THE FINGERPRINT

`evaluation_version` is `evx_` + the first 16 hex of a sha256 over the material
inputs, serialised canonically (sorted keys, no whitespace). Two evaluations are
comparable if and only if it matches; when it differs, the components above say
which part of the system moved.

WHAT IS DELIBERATELY NOT IN IT

  * timestamps and candidate identity — an evaluation of a different person at
    a different moment on an unchanged system IS comparable, and that is the
    entire question the fingerprint exists to answer.
  * `model_returned` — a per-PROCESS observation (see llm.py). Hashing it would
    make the identity depend on whether anyone happened to make a live call in
    this process, which is not a property of the evaluation. It is recorded, in
    full, one field away.

WHAT CAN NEVER BE IN IT

Secrets. `FEATURE_FLAGS` is a hard-coded allowlist of eight setting NAMES, so
a credential cannot arrive here by someone adding a config field — there is no
iteration over `settings`, no `model_dump()`, no prefix match.
`test_provenance_persists_no_secrets` scans a stored row for the live values of
the OpenAI key, the WhatsApp token, the app secret and the database URL.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from api import llm
from api.config import settings
from api.engine.question import QUESTION_POLICY_VERSION
from api.engine.scoring import SCORING_VERSION
from api.engine.signals import RUBRIC_VERSION
from api.schemas import ProvenanceOut
from api.taxonomy import taxonomy_hash, taxonomy_version

log = logging.getLogger("proofscreen.provenance")

APP_VERSION = "2.0.0"

# The settings that materially change what the interview does or what a number
# comes out as. ALLOWLIST BY NAME, never a dump of `settings`.
#
# Present: the five behavioural flags, the two size caps, and voice_weight —
# which is arithmetic in `claim_score` and therefore a scoring input, not a
# preference.
#
# Absent on purpose: every credential, `database_url`, `cors_origins`,
# `enable_dev_endpoints`, `require_api_key`, timeouts. None of them can move a
# score, and one of them is a secret.
FEATURE_FLAGS: tuple[str, ...] = (
    "adaptive_probing",
    "transfer_probe",
    "question_validation",
    "repair_turn",
    "score_inline",
    "voice_weight",
    "max_questions",
    "max_claims",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def code_version() -> str:
    """The build that produced an evaluation.

    Three sources, in order, and the third is the honest one:

      1. `BUILD_SHA` — set it at image build time. `.git` is in
         `.dockerignore`, so in the container this is the ONLY source.
      2. `.git/HEAD`, read directly. No subprocess: this runs at import in a
         web process, and shelling out at import is how startups get slow and
         flaky. Handles both a detached HEAD and a ref.
      3. The literal `"unknown"`.

    NOT a fabricated hash. A made-up SHA in a provenance record is worse than
    an absent one, because it looks like an answer.
    """
    declared = (settings.build_sha or "").strip()
    if declared:
        return declared[:40]

    head = _REPO_ROOT / ".git" / "HEAD"
    try:
        content = head.read_text(encoding="utf-8").strip()
        if content.startswith("ref: "):
            ref = (_REPO_ROOT / ".git" / content[5:].strip()).read_text().strip()
            return ref[:12]
        return content[:12]                      # detached HEAD
    except (OSError, ValueError):
        return "unknown"


@dataclass(frozen=True)
class Provenance:
    """One immutable stamp. Typed fields; two dicts, both with varying keys."""

    taxonomy_version: str
    taxonomy_hash: str
    rubric_version: str
    scoring_version: str
    question_policy_version: str
    prompt_versions: dict[str, str]
    code_version: str
    app_version: str
    llm_mode: str
    model_requested: str | None
    model_returned: str | None
    feature_flags: dict[str, str] = field(default_factory=dict)

    # --- identity ----------------------------------------------------------

    def material(self) -> dict:
        """Exactly what the fingerprint is computed over. Sorted, canonical."""
        return {
            "taxonomy_version": self.taxonomy_version,
            "taxonomy_hash": self.taxonomy_hash,
            "rubric_version": self.rubric_version,
            "scoring_version": self.scoring_version,
            "question_policy_version": self.question_policy_version,
            "prompt_versions": dict(sorted(self.prompt_versions.items())),
            "code_version": self.code_version,
            "app_version": self.app_version,
            "llm_mode": self.llm_mode,
            "model_requested": self.model_requested,
            "feature_flags": dict(sorted(self.feature_flags.items())),
        }

    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.material(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return "evx_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    # --- serialisation -----------------------------------------------------

    def to_columns(self) -> dict:
        """The `evaluations` provenance columns, ready to assign."""
        return {
            "taxonomy_version": self.taxonomy_version,
            "taxonomy_hash": self.taxonomy_hash,
            "rubric_version": self.rubric_version,
            "scoring_version": self.scoring_version,
            "question_policy_version": self.question_policy_version,
            "prompt_versions_json": json.dumps(
                dict(sorted(self.prompt_versions.items())), sort_keys=True
            ),
            "code_version": self.code_version,
            "app_version": self.app_version,
            "llm_mode": self.llm_mode,
            "model_requested": self.model_requested,
            "model_returned": self.model_returned,
            "feature_flags_json": json.dumps(
                dict(sorted(self.feature_flags.items())), sort_keys=True
            ),
            "evaluation_version": self.fingerprint(),
        }

    def to_out(self, stored_fingerprint: str | None = None) -> ProvenanceOut:
        """`stored_fingerprint` wins when given, and callers reading a row give
        it.

        A stamp read back from an evaluation must report the identity that was
        WRITTEN, not one recomputed from the columns. The two agree for a
        finalized row and differ for a draft, whose columns are empty — and a
        recomputed hash there would give an unfinished assessment a confident
        identity derived from nothing.
        """
        return ProvenanceOut(
            **{
                k: v
                for k, v in self.__dict__.items()
                if k in ProvenanceOut.model_fields
            },
            evaluation_version=(
                self.fingerprint() if stored_fingerprint is None else stored_fingerprint
            ),
        )


def _flag_values() -> dict[str, str]:
    """Allowlisted settings, stringified so one column shape holds all of them.

    `str()` rather than the raw value on purpose: `voice_weight` is a float and
    `max_questions` an int, and a fingerprint that changed when `0.1` was
    re-read as `0.10` would be noise dressed as drift.
    """
    out: dict[str, str] = {}
    for name in FEATURE_FLAGS:
        value = getattr(settings, name, None)
        out[name.upper()] = "" if value is None else str(value)
    return out


def current() -> Provenance:
    """The stamp as of right now. Cheap: hashes are cached, nothing is read."""
    return Provenance(
        taxonomy_version=taxonomy_version(),
        taxonomy_hash=taxonomy_hash(),
        rubric_version=RUBRIC_VERSION,
        scoring_version=SCORING_VERSION,
        question_policy_version=QUESTION_POLICY_VERSION,
        prompt_versions=llm.prompt_versions(),
        code_version=code_version(),
        app_version=APP_VERSION,
        llm_mode=settings.llm_mode,
        model_requested=settings.openai_model if settings.llm_enabled else None,
        model_returned=llm.model_returned(),
        feature_flags=_flag_values(),
    )


def from_row(row) -> Provenance:
    """Rebuild the stamp an evaluation was FINALIZED under, from its columns.

    Reading it back rather than recomputing is the whole point: replay compares
    the stamp that produced the number against the stamp in force today, and a
    `from_row` that quietly substituted current values would report no drift,
    ever.
    """

    def loads(payload: str | None) -> dict[str, str]:
        try:
            data = json.loads(payload or "{}")
        except (TypeError, ValueError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    return Provenance(
        taxonomy_version=row.taxonomy_version or "",
        taxonomy_hash=row.taxonomy_hash or "",
        rubric_version=row.rubric_version or "",
        scoring_version=row.scoring_version or "",
        question_policy_version=row.question_policy_version or "",
        prompt_versions=loads(row.prompt_versions_json),
        code_version=row.code_version or "unknown",
        app_version=row.app_version or "",
        llm_mode=row.llm_mode or "fixture",
        model_requested=row.model_requested,
        model_returned=row.model_returned,
        feature_flags=loads(row.feature_flags_json),
    )


def drift(earlier: Provenance, later: Provenance) -> list[tuple[str, str, str]]:
    """(field, then, now) for every MATERIAL input that moved.

    Material only — `model_returned` is excluded here for the same reason it is
    excluded from the fingerprint, and reporting it as drift would tell a
    support engineer the system changed when a colleague merely made a live
    call in a process that had made none.
    """
    a, b = earlier.material(), later.material()
    out: list[tuple[str, str, str]] = []
    for key in sorted(set(a) | set(b)):
        left, right = a.get(key), b.get(key)
        if left == right:
            continue
        if isinstance(left, dict) or isinstance(right, dict):
            left_map, right_map = left or {}, right or {}
            for inner in sorted(set(left_map) | set(right_map)):
                if left_map.get(inner) != right_map.get(inner):
                    out.append(
                        (
                            f"{key}.{inner}",
                            str(left_map.get(inner, "—")),
                            str(right_map.get(inner, "—")),
                        )
                    )
            continue
        out.append((key, str(left), str(right)))
    return out
