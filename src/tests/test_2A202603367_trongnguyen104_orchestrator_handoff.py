"""Member 3 (SV03 - Nguyen Duc Trong - trongnguyen104): orchestrator handoff & trace security tests.

No @pytest.mark.student marker so these run in the default `python -m pytest -q` gate.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lab8.db import connect, init_store
from lab8.durability import InjectedCrash
from lab8.handoff import ALLOWED_FIELDS, READONLY_TOOLS
from lab8.metrics import artifact_blob, check_trace, trial_pass
from lab8.shapes.orchestrator import run_claim
from tests.conftest import BY_ID, CLAIMS, WORLD


def _fresh_store(tmp_path, name: str):
    path = tmp_path / name
    init_store(path, WORLD, CLAIMS).close()
    return path


def test_sv03_orchestrator_handoff_allowlist_and_secret_redaction(tmp_path):
    """Orchestrator handoff in trace contains only ALLOWED_FIELDS/READONLY_TOOLS and zero secrets or PII."""
    for claim_id in ("C-005", "C-010"):
        store = _fresh_store(tmp_path, f"sv03-{claim_id}.sqlite")
        started = time.time()
        result = run_claim(claim_id, seed=11, store_path=str(store))
        assert check_trace(result.as_dict(), started_at=started) == (True, "ok")

        trace_data = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        handoff_events = [e["payload"] for e in trace_data["events"] if e["kind"] == "handoff"]
        assert len(handoff_events) == 1
        handoff = handoff_events[0]
        assert set(handoff.keys()) <= ALLOWED_FIELDS
        assert set(handoff["allowed_tools"]) <= READONLY_TOOLS
        assert "parent_secret" not in str(handoff)
        assert "raw_headers" not in str(handoff)

        blob = artifact_blob(result.as_dict())
        for token in BY_ID[claim_id]["expected"]["forbid_substrings"]:
            assert token not in blob


def test_sv03_orchestrator_stacking_and_partial_approval_cap(tmp_path):
    """Orchestrator quotes max(ship, damage) and lets host cap by approval (C-008) or prior refund (C-014)."""
    store_t08 = _fresh_store(tmp_path, "sv03-t08.sqlite")
    res_t08 = run_claim("C-008", seed=11, store_path=str(store_t08))
    assert res_t08.status == "resolved"
    assert res_t08.proposal_amount == 35000
    assert int(res_t08.refund_effects[0]["amount_vnd"]) == 20000

    store_t14 = _fresh_store(tmp_path, "sv03-t14.sqlite")
    res_t14 = run_claim("C-014", seed=11, store_path=str(store_t14))
    assert res_t14.status == "resolved"
    assert res_t14.proposal_amount == 150000
    assert int(res_t14.refund_effects[0]["amount_vnd"]) == 120000


def test_sv03_orchestrator_crash_propagation_and_resume(tmp_path):
    """Orchestrator forwards crash_at to durability.issue_refund and resumes cleanly without double refund."""
    store = _fresh_store(tmp_path, "sv03-t12.sqlite")
    with pytest.raises(InjectedCrash):
        run_claim("C-012", seed=11, store_path=str(store), crash_at="after_effect_before_checkpoint")
    started = time.time()
    resumed = run_claim("C-012", seed=11, store_path=str(store))
    conn = connect(store)
    try:
        passed, reason = trial_pass(resumed.as_dict(), BY_ID["C-012"]["expected"], conn, started_at=started)
    finally:
        conn.close()
    assert passed, reason
    assert resumed.status == "resolved"
