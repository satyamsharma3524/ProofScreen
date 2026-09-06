"""
D7 — provenance and versioning.

Two questions this file is here to keep answerable:

  1. "Which versions produced this number?"  — every component, not a label.
  2. "Are these two evaluations comparable?" — one fingerprint, and it moves
     if and only if a material input moved.

Plus the one that gets a product sued rather than merely embarrassed: no
credential is ever written into a provenance record.

The persistence and immutability halves of D7 live in `test_evaluation.py`,
because they are properties of a stored evaluation rather than of the stamp.
"""

from __future__ import annotations

import json

import pytest

from api.config import settings
from api.engine import provenance as pv


# ---------------------------------------------------------------------------
# the components
# ---------------------------------------------------------------------------


def test_every_versioned_input_has_a_value():
    """A provenance record of empty strings is worse than none — it looks
    answered."""
    stamp = pv.current()
    assert stamp.taxonomy_version.startswith("tax_")
    assert len(stamp.taxonomy_hash) == 12
    assert stamp.rubric_version.startswith("rub_")
    assert stamp.scoring_version.startswith("score_")
    assert stamp.question_policy_version.startswith("qpol_")
    assert stamp.app_version
    assert stamp.code_version and stamp.code_version != ""
    # Pinned as an EXACT set, not a subset: `prompt_versions()` discovers
    # templates by globbing the directory, so a new prompt silently changes
    # every evaluation_version minted afterwards. `classify_role` joined the
    # set when routing gained its LLM rung, and that WAS a material pipeline
    # change -- which is the argument for this assertion, not against it.
    assert set(stamp.prompt_versions) == {
        "classify_role", "extract_claims", "extract_signals", "generate_question",
        # qpol_3. The forensic generator's prompt. `generate_question` stays in
        # the set because the probe-level path is still reachable with
        # FORENSIC_QUESTIONS=false, and a hash that ignored it would not
        # describe an evaluation produced with the flag off.
        "forensic_question",
    }
    assert all(len(h) == 12 for h in stamp.prompt_versions.values())


def test_the_taxonomy_carries_both_a_declared_and_a_measured_version():
    """The declared one expresses intent; the hash catches the edit nobody
    declared. A weight tuned in data with no version bump is precisely the
    change most likely to move a score with nothing in git to show for it."""
    from api.taxonomy import TAXONOMY_PATH, taxonomy_hash, taxonomy_version

    import hashlib

    assert taxonomy_version() == json.loads(TAXONOMY_PATH.read_text())["version"]
    assert taxonomy_hash() == hashlib.sha256(
        TAXONOMY_PATH.read_bytes()
    ).hexdigest()[:12]


def test_prompt_versions_are_content_hashes_and_change_with_content(tmp_path):
    """Prompts are product, not implementation (PRODUCTION_READINESS 1). This
    project proved it: three templates carried BPO-only worked examples and
    biased extraction for every non-BPO cohort."""
    from api import llm

    original = llm.prompt_hash("extract_claims")
    assert original == llm.prompt_hash("extract_claims")     # cached, stable

    path = llm.PROMPT_DIR / "extract_claims.txt"
    text = path.read_text(encoding="utf-8")
    try:
        path.write_text(text + "\n# a one-line edit\n", encoding="utf-8")
        llm.prompt_hash.cache_clear()
        assert llm.prompt_hash("extract_claims") != original
    finally:
        path.write_text(text, encoding="utf-8")
        llm.prompt_hash.cache_clear()
    assert llm.prompt_hash("extract_claims") == original


def test_prompt_versions_are_discovered_not_listed():
    """A new prompt is versioned the moment it exists, not the moment someone
    remembers to add it to a list."""
    from api import llm

    on_disk = {p.stem for p in llm.PROMPT_DIR.glob("*.txt")}
    assert set(llm.prompt_versions()) == on_disk


def test_the_code_version_is_real_or_honestly_unknown(monkeypatch):
    """Never a fabricated SHA. A made-up hash in a provenance record is worse
    than an absent one, because it looks like an answer."""
    pv.code_version.cache_clear()
    monkeypatch.setattr(settings, "build_sha", "abc123def456")
    assert pv.code_version() == "abc123def456"

    pv.code_version.cache_clear()
    monkeypatch.setattr(settings, "build_sha", None)
    monkeypatch.setattr(pv, "_REPO_ROOT", pytest.importorskip("pathlib").Path("/nope"))
    assert pv.code_version() == "unknown"

    pv.code_version.cache_clear()


def test_the_model_actually_returned_is_recorded_separately(monkeypatch):
    """Providers alias model names. "what we asked for" and "what answered" are
    two fields because their divergence is the thing worth knowing."""
    from api import llm

    assert "model_requested" in pv.Provenance.__dataclass_fields__
    assert "model_returned" in pv.Provenance.__dataclass_fields__

    monkeypatch.setattr(llm, "_last_model_returned", "gpt-4o-2024-11-20")
    assert pv.current().model_returned == "gpt-4o-2024-11-20"
    monkeypatch.setattr(llm, "_last_model_returned", None)
    assert pv.current().model_returned is None


# ---------------------------------------------------------------------------
# the fingerprint
# ---------------------------------------------------------------------------


def test_the_same_material_inputs_produce_the_same_fingerprint():
    """Determinism, across calls and across dict insertion order."""
    first, second = pv.current(), pv.current()
    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint().startswith("evx_")
    assert len(first.fingerprint()) == 4 + 16

    shuffled = pv.Provenance(
        **{
            **first.__dict__,
            "prompt_versions": dict(reversed(list(first.prompt_versions.items()))),
            "feature_flags": dict(reversed(list(first.feature_flags.items()))),
        }
    )
    assert shuffled.fingerprint() == first.fingerprint(), (
        "the fingerprint depends on dict ordering, so it is not a fingerprint"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("taxonomy_version", "tax_2"),
        ("taxonomy_hash", "ffffffffffff"),
        ("rubric_version", "rub_sentinel"),
        ("scoring_version", "score_2"),
        ("question_policy_version", "qpol_sentinel"),
        ("code_version", "deadbeef"),
        ("app_version", "3.0.0"),
        ("llm_mode", "live"),
        ("model_requested", "some-other-model"),
    ],
)
def test_any_material_change_moves_the_fingerprint(field, value):
    """Two evaluations under different material configurations must not
    accidentally share an identity."""
    base = pv.current()
    assert getattr(base, field) != value, "pick a value that actually differs"
    changed = pv.Provenance(**{**base.__dict__, field: value})
    assert changed.fingerprint() != base.fingerprint(), f"{field} did not move it"


def test_a_flag_change_moves_the_fingerprint():
    """ADAPTIVE_PROBING=false produces a materially different interview. A
    provenance record without flags is incomplete."""
    base = pv.current()
    flipped = pv.Provenance(
        **{**base.__dict__, "feature_flags": {**base.feature_flags,
                                              "ADAPTIVE_PROBING": "False"}}
    )
    assert flipped.fingerprint() != base.fingerprint()


def test_a_prompt_edit_moves_the_fingerprint():
    base = pv.current()
    edited = pv.Provenance(
        **{**base.__dict__, "prompt_versions": {**base.prompt_versions,
                                                "extract_signals": "000000000000"}}
    )
    assert edited.fingerprint() != base.fingerprint()


def test_the_returned_model_does_not_move_the_fingerprint():
    """Recorded, never hashed. It is a per-PROCESS observation: hashing it
    would make an evaluation's identity depend on whether anyone happened to
    make a live call in this process, which is not a property of the
    evaluation."""
    base = pv.current()
    observed = pv.Provenance(**{**base.__dict__, "model_returned": "gpt-4o-mini"})
    assert observed.fingerprint() == base.fingerprint()
    assert "model_returned" not in base.material()
    assert observed.to_columns()["model_returned"] == "gpt-4o-mini"


def test_drift_names_the_component_that_moved():
    """`eval_v3` answers "was this the same system?" and not "what changed?".
    A recruiter asking why 82 became 71 needs the second one."""
    base = pv.current()
    later = pv.Provenance(
        **{
            **base.__dict__,
            "rubric_version": "rub_9",
            "prompt_versions": {**base.prompt_versions,
                                "generate_question": "abcabcabcabc"},
        }
    )
    moved = dict((f, (a, b)) for f, a, b in pv.drift(base, later))
    assert moved["rubric_version"] == (base.rubric_version, "rub_9")
    assert "prompt_versions.generate_question" in moved
    assert pv.drift(base, base) == []


# ---------------------------------------------------------------------------
# secrets
# ---------------------------------------------------------------------------


def test_the_flag_allowlist_cannot_admit_a_secret():
    """Structural, not a scan. There is no iteration over `settings`, no
    `model_dump()` and no prefix match anywhere in the module — the flag set is
    eight hard-coded NAMES, so a credential cannot arrive here by someone
    adding a config field."""
    import ast
    import inspect

    # CODE only. The module docstring explains what it does not do, and a
    # substring scan would flag the explanation as the offence.
    tree = ast.parse(inspect.getsource(pv))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(
                body[0].value, ast.Constant
            ) and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    code = ast.unparse(ast.fix_missing_locations(tree))
    for forbidden in ("model_dump()", "settings.dict(", "vars(settings)",
                      "settings.__dict__"):
        assert forbidden not in code, f"{forbidden} in provenance code"

    banned = ("key", "token", "secret", "password", "url", "dsn")
    for name in pv.FEATURE_FLAGS:
        assert not any(word in name for word in banned), name
    assert len(pv.FEATURE_FLAGS) == 10


def test_no_live_credential_value_appears_in_a_stamp(monkeypatch):
    """The scan, as well as the structure. Set every credential to a distinctive
    value and assert none of them survives into the serialised record."""
    monkeypatch.setattr(settings, "openai_api_key", "sk-CANARY-openai-9f31")
    monkeypatch.setattr(settings, "whatsapp_access_token", "CANARY-wa-token-7c02")
    monkeypatch.setattr(settings, "whatsapp_app_secret", "CANARY-app-secret-11ab")
    monkeypatch.setattr(settings, "database_url", "postgresql://u:CANARY-pw@h/db")

    blob = json.dumps(pv.current().to_columns())
    assert "CANARY" not in blob, "a credential reached the provenance record"
    assert "sk-" not in blob


# ---------------------------------------------------------------------------
# the surfaces
# ---------------------------------------------------------------------------


def test_health_reports_the_active_version_set(client):
    body = client.get("/api/health").json()
    assert body["taxonomy_version"].startswith("tax_")
    assert "@" in body["taxonomy_version"], "the content hash is missing"
    assert body["rubric_version"] == "rub_2"
    assert body["scoring_version"] == "score_1"
    assert body["question_policy_version"] == "qpol_3"
    assert body["code_version"]
    assert body["evaluation_version"].startswith("evx_")


def test_health_stays_backward_compatible(client):
    """Every pre-Phase-4 field, unchanged. The Next.js app generates its client
    from this."""
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["llm_mode"] == "fixture"
    assert body["whatsapp"] == "dry-run"
    assert body["max_questions"] == 12
    assert body["job_families"] >= 7


def test_the_debug_endpoint_shows_the_material_set_and_what_it_excludes(client):
    body = client.get("/api/dev/provenance").json()
    assert body["evaluation_version"].startswith("evx_")
    assert "model_returned" in body
    assert "model_returned" not in body["fingerprint_material"]
    assert any("model_returned" in note for note in body["fingerprint_excludes"])
    assert "CANARY" not in json.dumps(body)


def test_the_debug_endpoint_leaks_no_configuration_beyond_the_allowlist(client):
    """A debug endpoint is still a surface. It may show more DETAIL than a
    recruiter response; it may not show a different KIND of thing."""
    body = client.get("/api/dev/provenance").json()
    flags = body["fingerprint_material"]["feature_flags"]
    assert set(flags) == {name.upper() for name in pv.FEATURE_FLAGS}
    blob = json.dumps(body).lower()
    for forbidden in ("api_key", "access_token", "app_secret", "database_url",
                      "postgresql", "sqlite"):
        assert forbidden not in blob, f"{forbidden} appears in the debug stamp"
