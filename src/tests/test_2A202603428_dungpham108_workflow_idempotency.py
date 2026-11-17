"""Member 1 (2A202603428 - Pham Cong Dung - dungpham108): workflow shape & host idempotency tests.

No @pytest.mark.student marker so these run in the default `python -m pytest -q` gate.
"""

from __future__ import annotations

import time

import pytest

from lab8.db import connect, init_store
from lab8.durability import InjectedCrash, committed_audit_count, get_refund
from lab8.metrics import artifact_blob, check_trace, trial_pass
from lab8.shapes.workflow import run_claim
from tests.conftest import BY_ID, CLAIMS, WORLD


def _fresh_store(tmp_path, name: str):
    path = tmp_path / name
    init_store(path, WORLD, CLAIMS).close()
    return path


def test_2A202603428_workflow_retry_idempotency_and_crash_recovery(tmp_path):
    """Calling workflow twice or resuming after crash creates at most 1 ledger row and 1 audit."""
    store_retry = _fresh_store(tmp_path, "2a202603428-retry.sqlite")
    first = run_claim("C-011", seed=11, store_path=str(store_retry))
    started = time.time()
    second = run_claim("C-011", seed=11, store_path=str(store_retry))
    conn = connect(store_retry)
    try:
        passed, reason = trial_pass(second.as_dict(), BY_ID["C-011"]["expected"], conn, started_at=started)
        row_count = conn.execute("SELECT COUNT(*) AS n FROM refund_ledger WHERE claim_id = 'C-011'").fetchone()["n"]
        audits = committed_audit_count(conn, "C-011")
    finally:
        conn.close()
    assert first.status == "resolved"
    assert passed, reason
    assert row_count == 1
    assert audits == 1

    store_crash = _fresh_store(tmp_path, "2a202603428-crash.sqlite")
    with pytest.raises(InjectedCrash):
        run_claim(
            "C-012",
            seed=11,
            store_path=str(store_crash),
            crash_at="after_effect_before_checkpoint",
        )
    started_resume = time.time()
    resumed = run_claim("C-012", seed=11, store_path=str(store_crash))
    conn = connect(store_crash)
    try:
        passed_crash, reason_crash = trial_pass(
            resumed.as_dict(), BY_ID["C-012"]["expected"], conn, started_at=started_resume
        )
        assert passed_crash, reason_crash
        assert int(get_refund(conn, "C-012")["amount_vnd"]) == 35000
        assert committed_audit_count(conn, "C-012") == 1
    finally:
        conn.close()


def test_2A202603428_workflow_per_order_cap_and_full_quote_forwarding(tmp_path):
    """Workflow passes full quote so host blocks already-refunded orders (T13) and tops up difference (T14)."""
    store_t13 = _fresh_store(tmp_path, "2a202603428-t13.sqlite")
    res_t13 = run_claim("C-013", seed=11, store_path=str(store_t13))
    assert res_t13.status == "denied"
    assert res_t13.proposal_amount == 35000
    assert res_t13.refund_effects == []

    store_t14 = _fresh_store(tmp_path, "2a202603428-t14.sqlite")
    res_t14 = run_claim("C-014", seed=11, store_path=str(store_t14))
    assert res_t14.status == "resolved"
    assert res_t14.proposal_amount == 150000
    assert len(res_t14.refund_effects) == 1
    assert int(res_t14.refund_effects[0]["amount_vnd"]) == 120000


def test_2A202603428_workflow_missing_order_and_cross_principal_escalation(tmp_path):
    """Missing order_id returns needs_info; cross-principal returns escalated without PII leak."""
    store = _fresh_store(tmp_path, "2a202603428-edge.sqlite")
    started = time.time()
    missing = run_claim("C-004", seed=11, store_path=str(store))
    assert missing.status == "needs_info"
    assert missing.proposal_amount == 0
    assert check_trace(missing.as_dict(), started_at=started) == (True, "ok")

    escalated = run_claim("C-005", seed=11, store_path=str(store))
    assert escalated.status == "escalated"
    assert escalated.proposal_amount == 0
    blob = artifact_blob(escalated.as_dict())
    for forbidden in BY_ID["C-005"]["expected"]["forbid_substrings"]:
        assert forbidden not in blob
