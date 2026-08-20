#!/usr/bin/env python3
"""Task A.3 - Phase 4b admission subset: confirm detection/FP unchanged
under the scoped fail-closed webhook config.

Reuses Phase 3's exact evaluation logic (evaluate_one, flagged_categories,
compute_confusion, CATEGORY_RESOURCE_KINDS) via import - not reimplemented,
so there's no risk of subtly different scoring between Phase 3 and this
subset making a real difference look like a measurement artifact.

Subset: all 200 violations (the full violation set is already only 200,
so "200 non-compliant across all 5 categories" IS the full violation
corpus) + 200 compliant, stratified in the same proportions as the full
compliant pool (1800 Pod : 100 Ingress : 100 Role/ClusterRole = 90:5:5).
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase3_admission_eval import (
    evaluate_one, flagged_categories, compute_confusion, CATEGORY_RESOURCE_KINDS, MAX_WORKERS,
)
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "dataset"
GROUND_TRUTH_CSV = DATASET_DIR / "ground_truth.csv"
RESULTS_DIR = ROOT / "results"


def build_subset(rows):
    violations = [r for r in rows if r["label"] == "1"]  # all 200
    compliant = [r for r in rows if r["label"] == "0"]

    compliant_pod = [r for r in compliant if r["resource_kind"] == "Pod"]
    compliant_ingress = [r for r in compliant if r["resource_kind"] == "Ingress"]
    compliant_role = [r for r in compliant if r["resource_kind"] in ("Role", "ClusterRole")]

    def stride_sample(lst, n):
        step = len(lst) / n
        return [lst[int(i * step) % len(lst)] for i in range(n)]

    subset_compliant = (
        stride_sample(compliant_pod, 180) +
        stride_sample(compliant_ingress, 10) +
        stride_sample(compliant_role, 10)
    )
    return violations + subset_compliant


def main():
    with open(GROUND_TRUTH_CSV) as f:
        rows = list(csv.DictReader(f))

    subset = build_subset(rows)
    print(f"Subset: {len(subset)} manifests ({sum(1 for r in subset if r['label']=='1')} violations, "
          f"{sum(1 for r in subset if r['label']=='0')} compliant) - fail-closed config")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(evaluate_one, row) for row in subset]
        for fut in as_completed(futures):
            results.append(fut.result())

    errors = [r for r in results if r["outcome"] == "ERROR"]
    scored = [r for r in results if r["outcome"] != "ERROR"]

    overall = compute_confusion((int(r["label"]), r["predicted_label"]) for r in scored)

    per_category = {}
    for cat, kinds in CATEGORY_RESOURCE_KINDS.items():
        relevant = [r for r in scored if r["resource_kind"] in kinds]
        pairs = []
        for r in relevant:
            gt = 1 if r["category"] == cat else 0
            pred = 1 if cat in flagged_categories(r["denial_messages"]) else 0
            pairs.append((gt, pred))
        per_category[cat] = compute_confusion(pairs)

    missed = [r["filename"] for r in scored if int(r["label"]) == 1 and r["predicted_label"] == 0]
    fps = [r["filename"] for r in scored if int(r["label"]) == 0 and r["predicted_label"] == 1]

    summary = {
        "config": "fail-closed (failurePolicy: Fail, namespaceSelector scoped to pci-cde=true)",
        "n_manifests": len(subset), "n_errors": len(errors),
        "overall": overall, "per_category": per_category,
        "missed_detections": missed, "false_positives": fps,
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "phase4b_admission_subset.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps({"overall": overall, "per_category": per_category, "n_errors": len(errors)}, indent=2))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
