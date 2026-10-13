"""Run the full diagnosis pipeline on a fixed set of demo cases and count the failure modes.

    python -m scripts.eval_diagnosis --out artifacts/eval.json

Each case makes two live AMD Token Factory calls (diagnosis and verifier), so a full run
takes roughly 10 to 20 minutes. The detector output is deterministic; the LLM is not, so
compare totals across runs rather than single cases.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time

import pandas as pd

from app import config
from app.agent import diagnose, normalize_raw
from app.checks import check_sensor_claims, report_observations
from app.detector import Detector
from app.retriever import Retriever
from app.sensors import asset_name

# (unit, cycle): 6 warning and 4 critical points across all held-out units
CASES = [(97, 150), (97, 162), (97, 185), (98, 110), (98, 140),
         (99, 140), (99, 170), (100, 150), (96, 290), (96, 320)]


def run_case(detector: Detector, retriever: Retriever, demo: pd.DataFrame, unit: int, cycle: int) -> dict:
    g = demo[demo["unit"] == unit].sort_values("cycle")
    a = detector.assess(g[g["cycle"] <= cycle])
    row = {"case": f"{asset_name(unit)}@{cycle}", "detector_severity": a["severity"]}
    t0 = time.perf_counter()
    try:
        report, _evidence, meta = diagnose(a, retriever)
    except Exception as err:  # count it, keep going
        return {**row, "error": f"{type(err).__name__}: {err}", "seconds": round(time.perf_counter() - t0, 1)}
    v = report.verification
    items = [*report.likely_causes, *report.recommended_actions]
    return {
        **row,
        "seconds": round(time.perf_counter() - t0, 1),
        "model": meta.get("model"),
        "severity": report.severity,
        "confidence": report.confidence,
        "escalate": report.escalate,
        "work_order_priority": report.work_order.priority if report.work_order else None,
        "causes": len(report.likely_causes),
        "actions": len(report.recommended_actions),
        "uncited_items": sum(1 for i in items if not i.citations),
        "removed_citations": sum(1 for n in report.guardrail_notes if n.startswith("Removed citations")),
        "sensor_mismatches": check_sensor_claims(report_observations(report), a),
        "verifier_supported": v.get("supported"),
        "verifier_failed_checks": len(v.get("unsupported_claims") or []) + len(v.get("invented_values") or [])
        + len(v.get("safety_issues") or []),
        "observations": report_observations(report),
        "guardrail_notes": report.guardrail_notes,
    }


def totals(rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    return {
        "cases": len(rows),
        "errors": len(rows) - len(ok),
        "median_seconds": round(statistics.median(r["seconds"] for r in ok), 1) if ok else None,
        "max_seconds": max((r["seconds"] for r in ok), default=None),
        "cases_with_uncited_items": sum(1 for r in ok if r["uncited_items"]),
        "cases_with_removed_citations": sum(1 for r in ok if r["removed_citations"]),
        "cases_with_sensor_mismatch": sum(1 for r in ok if r["sensor_mismatches"]),
        "verifier_supported": sum(1 for r in ok if r["verifier_supported"] is True),
        "critical_cases_escalated_p1": sum(1 for r in ok if r["detector_severity"] == "critical"
                                           and r["escalate"] and r["work_order_priority"] == "P1"),
        "critical_cases": sum(1 for r in ok if r["detector_severity"] == "critical"),
    }


def rescore(path: str) -> None:
    """Re-run the sensor check on saved observations (no model calls), after the checker changes."""
    with open(path, encoding="utf-8") as f:
        result = json.load(f)
    detector, demo = Detector(), pd.read_csv(config.DEMO_DATA)
    for r in result["cases"]:
        if "error" in r:
            continue
        unit, cycle = int(r["case"].split("@")[0][3:]), int(r["case"].split("@")[1])
        g = demo[demo["unit"] == unit].sort_values("cycle")
        a = detector.assess(g[g["cycle"] <= cycle])
        r["sensor_mismatches"] = check_sensor_claims(normalize_raw({"o": r["observations"]})["o"], a)
    result["totals"] = totals(result["cases"])
    result["rescored"] = "sensor_mismatches recomputed from saved observations with the current checker"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result["totals"], indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(config.ARTIFACTS / "eval.json"))
    ap.add_argument("--rescore", action="store_true", help="recheck saved results in --out, no model calls")
    args = ap.parse_args()
    if args.rescore:
        return rescore(args.out)
    detector, retriever = Detector(), Retriever()
    demo = pd.read_csv(config.DEMO_DATA)
    rows = []
    for unit, cycle in CASES:
        r = run_case(detector, retriever, demo, unit, cycle)
        rows.append(r)
        print(f"{r['case']:12s} {r.get('seconds', 0):6.1f}s  "
              + (r["error"][:80] if "error" in r else
                 f"uncited={r['uncited_items']} mismatches={len(r['sensor_mismatches'])} "
                 f"verifier={r['verifier_supported']} conf={r['confidence']}"), flush=True)
    result = {"model": config.AMD_MODEL, "fallbacks": config.AMD_FALLBACK_MODELS,
              "totals": totals(rows), "cases": rows}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result["totals"], indent=2))


if __name__ == "__main__":
    main()
