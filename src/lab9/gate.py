"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems = []

    # 1. Any metric value in pr["metrics"] that is NaN or inf
    for mid, val in pr.get("metrics", {}).items():
        if isinstance(val, (int, float)):
            if math.isnan(val) or math.isinf(val):
                problems.append(f"metric {mid} is {val}")

    # 2. len(pr["rows"]) != manifest items x len(manifest seeds)
    manifest = pr.get("manifest", {})
    expected_count = manifest.get("items", 0) * len(manifest.get("seeds", []))
    rows = pr.get("rows", [])
    if len(rows) != expected_count:
        problems.append(f"row count {len(rows)} != expected {expected_count} (items x seeds)")

    # 3. the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
    pr_pairs = [(r.get("item_id"), r.get("seed")) for r in rows]
    base_pairs = [(r.get("item_id"), r.get("seed")) for r in base.get("rows", [])]
    if len(pr_pairs) != len(set(pr_pairs)):
        problems.append("duplicate (item_id, seed) rows detected")
    if set(pr_pairs) != set(base_pairs):
        problems.append("PR (item_id, seed) set differs from baseline")

    # 4. pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is None
    if pr.get("evaluator_failures"):
        problems.append(f"evaluator_failures: {pr['evaluator_failures']}")
    from lab9.graders import GRADERS
    graded_metrics = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    for r in rows:
        for gm in graded_metrics:
            if r.get(gm) is None:
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} has None for metric {gm}")
                break

    # 5. an item's slice tags in PR rows differ from the baseline's
    base_slices = {r.get("item_id"): tuple(sorted(r.get("slices") or [])) for r in base.get("rows", [])}
    for r in rows:
        iid = r.get("item_id")
        if iid in base_slices:
            pr_sl = tuple(sorted(r.get("slices") or []))
            if pr_sl != base_slices[iid]:
                problems.append(f"item {iid} slices {pr_sl} differ from baseline {base_slices[iid]}")
                break

    # 6. base_spec given and a threshold in spec is LOOSER than in base_spec for the same eval-set version
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        base_m_by_id = {m["id"]: m for m in base_spec.get("metrics", [])}
        for mid, bm in base_m_by_id.items():
            sm = next((m for m in spec.get("metrics", []) if m["id"] == mid), None)
            if sm is None:
                problems.append(f"metric {mid} removed from spec (ratchet)")
                continue
            if bm.get("blocking") and not sm.get("blocking"):
                problems.append(f"metric {mid} made non-blocking (ratchet)")
            b_th = bm.get("threshold", {})
            s_th = sm.get("threshold", {})
            if "min" in b_th:
                if "min" not in s_th or s_th["min"] < b_th["min"] - 1e-9:
                    problems.append(f"metric {mid} min threshold loosened (ratchet)")
            if "max" in b_th:
                if "max" not in s_th or s_th["max"] > b_th["max"] + 1e-9:
                    problems.append(f"metric {mid} max threshold loosened (ratchet)")
            if b_th.get("no_significant_drop") and not s_th.get("no_significant_drop"):
                problems.append(f"metric {mid} dropped no_significant_drop requirement (ratchet)")

        base_sl_by_name = {sl["name"]: sl for sl in base_spec.get("slices", [])}
        for sname, bsl in base_sl_by_name.items():
            ssl = next((sl for sl in spec.get("slices", []) if sl["name"] == sname), None)
            if ssl is None:
                problems.append(f"slice {sname} removed from spec (ratchet)")
                continue
            if bsl.get("blocking") and not ssl.get("blocking"):
                problems.append(f"slice {sname} made non-blocking (ratchet)")
            if "min" in bsl:
                if "min" not in ssl or ssl["min"] < bsl["min"] - 1e-9:
                    problems.append(f"slice {sname} min threshold loosened (ratchet)")
            if bsl.get("no_significant_drop") and not ssl.get("no_significant_drop"):
                problems.append(f"slice {sname} dropped no_significant_drop (ratchet)")

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices", []):
        name = sl["name"]
        metric = sl["metric"]
        slice_id = f"slice:{name}/{metric}"
        pr_items = per_item(pr, metric, slice_name=name)
        if not pr_items:
            continue
        val = sum(pr_items.values()) / len(pr_items)
        fail = False
        note = ""
        if "min" in sl and val < sl["min"]:
            fail = True
        if sl.get("no_significant_drop"):
            base_items = per_item(base, metric, slice_name=name)
            keys = sorted(set(pr_items) & set(base_items))
            if keys:
                d, lo, hi = stats.paired_bootstrap([pr_items[k] for k in keys], [base_items[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    fail = True
        if fail and sl.get("blocking", True):
            blocked.append(slice_id)
        verdict = "BLOCK" if (fail and sl.get("blocking", True)) else ("warn" if fail else "ok")
        lines.append(f"  {slice_id:<28} {val:<8.4f} {json.dumps({k: v for k, v in sl.items() if k not in ('name', 'metric')}):<34} {note:<28} {verdict}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr.get('run_id')} vs main {base.get('run_id')} · eval set {pr['manifest']['eval_set_sha']}")
    for line in lines:
        print(line)
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
