#!/usr/bin/env python3
"""Evaluate the adversarial/edge-case supplement against live Gatekeeper.

Sequential (only 18 cases, no need for concurrency), --dry-run=server so
nothing is persisted. Reports each case individually against its documented
hypothesis - the point here is qualitative (which specific gaps are real),
not just an aggregate number.
"""
import csv
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# NOTE: relocated for the reproducibility artifact - matches
# dataset/generate_adversarial_dataset.py's new output location.
DATASET_DIR = ROOT / "dataset" / "adversarial"
GROUND_TRUTH_CSV = ROOT / "dataset" / "ground_truth_adversarial.csv"
RESULTS_DIR = ROOT / "results"
OUT_CSV = RESULTS_DIR / "adversarial_results.csv"

ENV = os.environ.copy()
ENV["AWS_PROFILE"] = "claude-code"


def evaluate_one(row):
    path = DATASET_DIR / row["filename"]
    proc = subprocess.run(
        ["kubectl", "apply", "--dry-run=server", "-f", str(path)],
        capture_output=True, text=True, env=ENV,
    )
    stderr = proc.stderr.strip()
    if proc.returncode == 0:
        outcome, predicted, msg = "ADMITTED", 0, ""
    elif "admission webhook" in stderr and "denied" in stderr:
        outcome, predicted, msg = "DENIED", 1, stderr.replace("\n", " | ")
    else:
        outcome, predicted, msg = "ERROR", None, stderr.replace("\n", " | ")
    return outcome, predicted, msg


def main():
    with open(GROUND_TRUTH_CSV) as f:
        rows = list(csv.DictReader(f))

    results = []
    for row in rows:
        outcome, predicted, msg = evaluate_one(row)
        expected = int(row["expected_label"])
        if predicted is None:
            verdict = "ERROR"
        elif expected == 1 and predicted == 1:
            verdict = "CAUGHT (policy generalized)"
        elif expected == 1 and predicted == 0:
            verdict = "GAP CONFIRMED (bypass succeeded)"
        elif expected == 0 and predicted == 0:
            verdict = "OK (true negative)"
        else:
            verdict = "FALSE POSITIVE (sanity case wrongly denied)"
        results.append({**row, "outcome": outcome, "predicted_label": predicted,
                         "denial_message": msg, "verdict": verdict})
        print(f"{row['filename']:45s} expected={expected} predicted={predicted}  {verdict}")

    RESULTS_DIR.mkdir(exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    n_gap = sum(1 for r in results if r["verdict"].startswith("GAP"))
    n_caught = sum(1 for r in results if r["verdict"].startswith("CAUGHT"))
    n_fp = sum(1 for r in results if r["verdict"].startswith("FALSE"))
    print(f"\n{n_gap} confirmed gaps, {n_caught} caught (generalized), {n_fp} false positives on sanity cases")
    print(f"Raw results: {OUT_CSV}")


if __name__ == "__main__":
    main()
