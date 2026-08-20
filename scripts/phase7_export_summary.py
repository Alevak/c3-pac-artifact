#!/usr/bin/env python3
"""Phase 7 - Export: consolidate all phases' raw results into one summary.

Reads only from the raw files each phase already wrote under results/ -
never recomputes or re-estimates a number. If a phase's raw file is
missing, that section is explicitly marked missing rather than omitted
silently, so a partial run is visible as partial.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"


def load_json(name):
    p = RESULTS_DIR / name
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def load_csv(name):
    p = RESULTS_DIR / name
    if not p.exists():
        return None
    with open(p) as f:
        return list(csv.DictReader(f))


def main():
    summary = {"note": "Every number below is read directly from this phase's own raw results file - see 'source' fields. Nothing here is recomputed or estimated."}

    p3 = load_json("phase3_admission_summary.json")
    adv = load_csv("adversarial_results.csv")
    summary["phase3_admission_evaluation"] = {
        "source": "results/phase3_admission_summary.json + results/phase3_admission_raw.csv",
        "status": "complete" if p3 else "MISSING",
        "main_corpus": {
            "n_manifests": p3["n_manifests"], "n_errors": p3["n_errors"],
            "overall": p3["overall"], "per_category": p3["per_category"],
        } if p3 else None,
        "adversarial_supplement": {
            "source": "results/adversarial_results.csv",
            "n_cases": len(adv),
            "n_gaps_confirmed": sum(1 for r in adv if r["verdict"].startswith("GAP")),
            "n_caught_generalized": sum(1 for r in adv if r["verdict"].startswith("CAUGHT")),
            "n_sanity_ok": sum(1 for r in adv if r["verdict"].startswith("OK")),
            "n_sanity_false_positive": sum(1 for r in adv if r["verdict"].startswith("FALSE")),
        } if adv else None,
    }

    p4 = load_json("phase4_latency.json")
    summary["phase4_latency"] = {
        "source": "results/phase4_latency.json",
        "status": "complete" if p4 else "MISSING",
        "note": "webhook_histogram = Gatekeeper's own Prometheus histogram (policy-engine-only latency). client_observed = kubectl round-trip incl. process spawn + network (NOT the same thing - see Phase 4 report).",
        "tiers": [
            {
                "tier": t["tier"], "concurrency": t["concurrency"], "n_requests": t["n_requests"],
                "webhook_histogram_ms": t["webhook_histogram"],
                "client_observed_ms": t["client_observed"],
            } for t in p4
        ] if p4 else None,
    }

    p5 = load_json("phase5_drift.json")
    summary["phase5_drift_detection"] = {
        "source": "results/phase5_drift.json",
        "status": "complete" if p5 else "MISSING",
        "audit_interval_seconds": p5["audit_interval_seconds"] if p5 else None,
        "trials": p5["trials"] if p5 else None,
        "median_latency_seconds": (
            sorted([t["latency_seconds"] for t in p5["trials"] if t["outcome"] == "DETECTED"])[
                len([t for t in p5["trials"] if t["outcome"] == "DETECTED"]) // 2
            ] if p5 and any(t["outcome"] == "DETECTED" for t in p5["trials"]) else None
        ),
        "caveat": "n=3 trials - small sample, wide confidence interval. Latency structurally bounded by the 60s periodic audit cycle, not a reactive watch.",
    }

    p6 = load_json("phase6_ci_overhead.json")
    summary["phase6_ci_overhead"] = {
        "source": "results/phase6_ci_overhead.json",
        "status": "complete" if p6 else "MISSING",
        "batches": p6,
        "note": "Baseline = same conftest binary against an empty policy dir, isolating the policy rules' own added cost from conftest's fixed startup cost. Relative % figures are large mainly because baseline is tiny (tens of ms) - see absolute ms overhead for real-world CI planning.",
        "known_policy_limitations_carried_over": [
            "req7_no_wildcard_rbac.rego only matches kind==ClusterRole, not Role (inherited from the original policy library, not introduced by the conftest input-shape adaptation)",
            "req1_network_isolation / req10_audit_logging test controls this corpus wasn't designed to satisfy (external NetworkPolicy data dependency / an audit-logging label no generated manifest sets)",
        ],
    }

    dataset_gt = RESULTS_DIR.parent / "dataset" / "ground_truth.csv"
    summary["phase2_dataset"] = {
        "source": "dataset/ground_truth.csv (corpus itself, not results/ - it's the input, not a measurement)",
        "status": "complete" if dataset_gt.exists() else "MISSING",
    }

    out_path = RESULTS_DIR / "summary_all_phases.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Saved consolidated summary: {out_path}")

    missing = [k for k, v in summary.items() if isinstance(v, dict) and v.get("status") == "MISSING"]
    if missing:
        print(f"\nWARNING - missing phases (not filled with estimates, left explicit): {missing}")
    else:
        print("\nAll phases present.")

    print("\nFiles in results/:")
    for p in sorted(RESULTS_DIR.iterdir()):
        if p.is_file():
            print(f"  {p.name} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
