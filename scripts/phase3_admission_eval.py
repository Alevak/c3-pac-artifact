#!/usr/bin/env python3
"""Phase 3 - Admission evaluation.

Applies every manifest in dataset/ against the live Gatekeeper admission
webhook via `kubectl apply --dry-run=server`, records the raw admit/deny
outcome, joins against ground_truth.csv, and computes detection rate /
false-positive rate both in aggregate and per violation category.

Why --dry-run=server, not a real apply: it round-trips through the full API
server pipeline INCLUDING the ValidatingWebhookConfiguration (so Gatekeeper's
decision is identical to a real apply), but never persists the object. That
means no scheduling, no cluster capacity concerns from the ~1920 Pod objects
in the corpus, and nothing to clean up afterward.

Two levels of detection reported, both real, answering different questions:
  - "overall": object-level admit/deny (matches what an operator would see -
    did the webhook block it, for any reason).
  - "per_category": fine-grained, parsed from the actual violation message(s)
    Gatekeeper returned. This matters because 5 of 7 constraints all target
    kind=Pod simultaneously, so a Pod's object-level "DENIED" doesn't by
    itself say *which* dimension triggered it. Every compliant row also
    contributes to every category whose constraint targets its resource kind
    (e.g. a compliant Pod is a true-negative test case for network AND
    secconfig AND images at once), not just its own nominal category.

Concurrency here (default 16 workers) exists purely to keep this phase's
wall-clock time reasonable. It is NOT the Phase 4 concurrent-load latency
measurement - that is a separate, deliberately controlled experiment.
"""
import csv
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "dataset"
GROUND_TRUTH_CSV = DATASET_DIR / "ground_truth.csv"
RESULTS_DIR = ROOT / "results"
RAW_CSV = RESULTS_DIR / "phase3_admission_raw.csv"
SUMMARY_JSON = RESULTS_DIR / "phase3_admission_summary.json"

MAX_WORKERS = 16

ENV = os.environ.copy()
ENV["AWS_PROFILE"] = "claude-code"

# Keyword -> category, taken verbatim from the violation msg templates in
# policies/gatekeeper/templates/*.yaml. Used to attribute WHICH constraint(s)
# fired on a given manifest, independent of the coarse admit/deny outcome.
CATEGORY_KEYWORDS = {
    "network": ["hostNetwork not allowed"],
    "secconfig": ["Privileged container", "hostPath volume", "running as root"],
    "images": ["Unapproved image"],
    "tls": ["missing or empty TLS"],
    "rbac": ["Wildcard resources in role", "Wildcard verbs in role"],
}

# Which resource kind each category's constraint actually targets - defines
# which rows are "relevant" (i.e. valid true-negative candidates) for that
# category's confusion matrix.
CATEGORY_RESOURCE_KINDS = {
    "network": {"Pod"},
    "secconfig": {"Pod"},
    "images": {"Pod"},
    "tls": {"Ingress"},
    "rbac": {"Role", "ClusterRole"},
}


def flagged_categories(denial_messages: str) -> set:
    flagged = set()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in denial_messages for kw in keywords):
            flagged.add(cat)
    return flagged


def evaluate_one(row: dict) -> dict:
    path = DATASET_DIR / row["filename"]
    t0 = time.perf_counter()
    proc = subprocess.run(
        ["kubectl", "apply", "--dry-run=server", "-f", str(path)],
        capture_output=True, text=True, env=ENV,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    stderr = proc.stderr.strip()

    if proc.returncode == 0:
        outcome = "ADMITTED"
        predicted_label = 0
        denial_msgs = ""
    elif "admission webhook" in stderr and "denied" in stderr:
        outcome = "DENIED"
        predicted_label = 1
        denial_msgs = stderr.replace("\n", " | ")
    else:
        outcome = "ERROR"
        predicted_label = None
        denial_msgs = stderr.replace("\n", " | ")

    return {
        **row,
        "outcome": outcome,
        "predicted_label": predicted_label,
        "latency_ms": round(latency_ms, 2),
        "denial_messages": denial_msgs,
    }


def confusion(pairs):
    """pairs: iterable of (ground_truth_label:int, predicted_label:int)."""
    tp = sum(1 for g, p in pairs if g == 1 and p == 1)
    return tp


def compute_confusion(pairs):
    pairs = list(pairs)
    tp = sum(1 for g, p in pairs if g == 1 and p == 1)
    fn = sum(1 for g, p in pairs if g == 1 and p == 0)
    fp = sum(1 for g, p in pairs if g == 0 and p == 1)
    tn = sum(1 for g, p in pairs if g == 0 and p == 0)
    detection_rate = tp / (tp + fn) if (tp + fn) else None
    fpr = fp / (fp + tn) if (fp + tn) else None
    precision = tp / (tp + fp) if (tp + fp) else None
    return {
        "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "detection_rate": detection_rate,
        "false_positive_rate": fpr,
        "precision": precision,
        "n": len(pairs),
    }


def main():
    with open(GROUND_TRUTH_CSV) as f:
        rows = list(csv.DictReader(f))

    print(f"Evaluating {len(rows)} manifests against live Gatekeeper admission control "
          f"({MAX_WORKERS} parallel workers, --dry-run=server, nothing persisted)...")
    t_start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(evaluate_one, row) for row in rows]
        for i, fut in enumerate(as_completed(futures), 1):
            results.append(fut.result())
            if i % 200 == 0:
                print(f"  {i}/{len(rows)} done ({time.time()-t_start:.0f}s elapsed)")
    elapsed = time.time() - t_start
    print(f"Done in {elapsed:.0f}s")

    order = {row["filename"]: idx for idx, row in enumerate(rows)}
    results.sort(key=lambda r: order[r["filename"]])

    RESULTS_DIR.mkdir(exist_ok=True)
    fieldnames = list(rows[0].keys()) + ["outcome", "predicted_label", "latency_ms", "denial_messages"]
    with open(RAW_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)
    print(f"Raw per-manifest results: {RAW_CSV}")

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

    missed_detections = [r["filename"] for r in scored if int(r["label"]) == 1 and r["predicted_label"] == 0]
    false_positives = [r["filename"] for r in scored if int(r["label"]) == 0 and r["predicted_label"] == 1]

    summary = {
        "n_manifests": len(rows),
        "n_errors": len(errors),
        "error_filenames": [r["filename"] for r in errors],
        "elapsed_seconds": round(elapsed, 1),
        "overall": overall,
        "per_category": per_category,
        "missed_detections": missed_detections,
        "false_positives": false_positives,
    }
    with open(SUMMARY_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nSummary: {SUMMARY_JSON}")
    print(json.dumps({"overall": overall, "per_category": per_category, "n_errors": len(errors)}, indent=2))
    if missed_detections:
        print(f"\nMISSED DETECTIONS ({len(missed_detections)}):")
        for f_ in missed_detections:
            print(f"  {f_}")
    if false_positives:
        print(f"\nFALSE POSITIVES ({len(false_positives)}):")
        for f_ in false_positives:
            print(f"  {f_}")
    if errors:
        print(f"\nERRORS ({len(errors)}) - not scored, investigate:")
        for r in errors:
            print(f"  {r['filename']}: {r['denial_messages'][:200]}")


if __name__ == "__main__":
    main()
