#!/usr/bin/env python3
"""Task B - OVER metric: relative CI pipeline overhead from Conftest.

OVER (as defined in the manuscript) = relative increase in pipeline
execution time due to Conftest checks = (T_with_conftest - T_baseline) /
T_baseline.

Phase 6 measured the ABSOLUTE cost (~1.06ms/file) but never established
T_baseline, so no relative metric could be computed. This fixes that.

BASELINE METHODOLOGY - read before trusting the numbers below:

Primary baseline (MEASURED, not estimated): `kubectl create --dry-run=client
--validate=false` against the same file batch. This is a real, timed
measurement of "manifest is well-formed YAML/structurally valid K8s
objects" - the step a Conftest policy gate would realistically be inserted
next to in a CI pipeline.

IMPORTANT - `create` was chosen over `apply` after verifying network
behavior directly with `-v=6`: `kubectl apply --dry-run=client`, even with
--validate=false, still does a live GET of the target object AND its
namespace against the real API server (needed for apply's three-way merge
logic) - confirmed by inspecting request logs, and consistent with Phase 6's
own 2000-file baseline run taking 142s wall time at only 3% CPU, a classic
network-wait signature. That makes `apply` unsuitable here: Task B has to
run identically before or after `terraform destroy`. `kubectl create
--dry-run=client` was verified (same -v=6 check, zero GET/POST logged) to
make NO network calls at all - it only needs `create` doesn't merge against
existing state, so there's nothing to fetch. This is genuinely offline-safe.

This baseline does NOT represent a full CI pipeline (no build, no unit
tests, no container image build) - only the manifest-validation step
Conftest would sit alongside.

Secondary reference points (ESTIMATES, explicitly not measured): a few
commonly-cited illustrative full-pipeline durations (2/5/10 minutes) are
included ONLY to show how the absolute overhead compares to a realistic
end-to-end CI job. These are round illustrative numbers from common
practice, NOT something this script measured, and are labeled as such in
the output - do not read them as measured data.
"""
import csv
import json
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "dataset"
GROUND_TRUTH_CSV = DATASET_DIR / "ground_truth.csv"
REAL_POLICY_DIR = ROOT / "policies" / "conftest"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

BATCH_SIZES_AND_REPEATS = [
    (10, 15),
    (50, 12),
    (100, 10),
    (500, 8),
    (2200, 6),  # upper-bound scaling ceiling, not a "realistic" single PR size
]

ILLUSTRATIVE_FULL_PIPELINE_MINUTES = [2, 5, 10]  # explicitly NOT measured


def stratified_sample(rows, n):
    if n >= len(rows):
        return rows
    step = len(rows) / n
    return [rows[int(i * step) % len(rows)] for i in range(n)]


def time_baseline_validation(files):
    """kubectl create --dry-run=client --validate=false - verified via -v=6
    to make zero network calls (unlike `apply`, which always GETs current
    state even in dry-run). This IS the T_baseline."""
    file_args = [str(DATASET_DIR / f) for f in files]
    t0 = time.perf_counter()
    subprocess.run(
        ["kubectl", "create", "--dry-run=client", "--validate=false", *sum([["-f", f] for f in file_args], []), "-o", "name"],
        capture_output=True, text=True,
    )
    return (time.perf_counter() - t0) * 1000


def time_conftest(files):
    file_args = [str(DATASET_DIR / f) for f in files]
    t0 = time.perf_counter()
    subprocess.run(
        ["conftest", "test", *file_args, "-p", str(REAL_POLICY_DIR), "--all-namespaces", "-o", "json"],
        capture_output=True, text=True,
    )
    return (time.perf_counter() - t0) * 1000


def mean_p95(values):
    s = sorted(values)
    return {
        "mean_ms": round(statistics.mean(s), 1),
        "p95_ms": round(s[int(len(s) * 0.95)] if len(s) > 1 else s[0], 1),
        "n": len(s),
    }


def main():
    with open(GROUND_TRUTH_CSV) as f:
        rows = list(csv.DictReader(f))

    results = []
    for n_files, repeats in BATCH_SIZES_AND_REPEATS:
        sample = stratified_sample(rows, n_files)
        filenames = [r["filename"] for r in sample]
        print(f"\n=== Batch size {n_files}, {repeats} repeats ===")

        baseline_times = [time_baseline_validation(filenames) for _ in range(repeats)]
        conftest_times = [time_conftest(filenames) for _ in range(repeats)]

        b_stats = mean_p95(baseline_times)
        c_stats = mean_p95(conftest_times)

        over_mean_pct = (c_stats["mean_ms"] - b_stats["mean_ms"]) / b_stats["mean_ms"] * 100 if b_stats["mean_ms"] else None
        over_p95_pct = (c_stats["p95_ms"] - b_stats["p95_ms"]) / b_stats["p95_ms"] * 100 if b_stats["p95_ms"] else None

        row = {
            "batch_size": n_files, "repeats": repeats,
            "realistic_ci_batch": n_files != 2200,
            "T_baseline": b_stats, "T_with_conftest": c_stats,
            "OVER_mean_pct": round(over_mean_pct, 1) if over_mean_pct is not None else None,
            "OVER_p95_pct": round(over_p95_pct, 1) if over_p95_pct is not None else None,
            "absolute_overhead_mean_ms": round(c_stats["mean_ms"] - b_stats["mean_ms"], 1),
        }
        results.append(row)
        print(json.dumps(row, indent=2))

    illustrative = []
    for minutes in ILLUSTRATIVE_FULL_PIPELINE_MINUTES:
        pipeline_ms = minutes * 60 * 1000
        for r in results:
            if not r["realistic_ci_batch"]:
                continue
            over_vs_full_pipeline_pct = r["absolute_overhead_mean_ms"] / pipeline_ms * 100
            illustrative.append({
                "illustrative_pipeline_minutes": minutes, "NOT_MEASURED": True,
                "batch_size": r["batch_size"],
                "conftest_overhead_ms": r["absolute_overhead_mean_ms"],
                "overhead_as_pct_of_illustrative_pipeline": round(over_vs_full_pipeline_pct, 3),
            })

    output = {
        "definition": "OVER = (T_with_conftest - T_baseline) / T_baseline * 100%",
        "baseline_methodology": (
            "T_baseline = MEASURED: `kubectl create --dry-run=client --validate=false` "
            "against the same file batch (pure client-side structural check). `apply` "
            "was tried first and rejected: verified via -v=6 that it always does a live "
            "GET of the object + namespace even in dry-run mode (needed for its 3-way "
            "merge), which is not offline-safe and explains Phase 6's own slow 2000-file "
            "baseline run (142s at 3% CPU - a network-wait signature). `create` was "
            "verified (same -v=6 check) to make zero network calls, so this runs "
            "identically before or after terraform destroy. This represents the "
            "manifest-validation step Conftest would be inserted next to, NOT a full CI "
            "pipeline (no build/test/image-build steps are measured or estimated here)."
        ),
        "batches": results,
        "illustrative_full_pipeline_context": {
            "note": "NOT MEASURED - round illustrative pipeline durations from common practice, included only for scale/context. Do not cite as measured data.",
            "comparisons": illustrative,
        },
    }

    out_path = RESULTS_DIR / "phase6b_over_metric.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    out_csv = RESULTS_DIR / "phase6b_over_metric.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["batch_size", "realistic_ci_batch", "repeats", "T_baseline_mean_ms", "T_baseline_p95_ms",
                     "T_conftest_mean_ms", "T_conftest_p95_ms", "OVER_mean_pct", "OVER_p95_pct", "absolute_overhead_mean_ms"])
        for r in results:
            w.writerow([r["batch_size"], r["realistic_ci_batch"], r["repeats"],
                         r["T_baseline"]["mean_ms"], r["T_baseline"]["p95_ms"],
                         r["T_with_conftest"]["mean_ms"], r["T_with_conftest"]["p95_ms"],
                         r["OVER_mean_pct"], r["OVER_p95_pct"], r["absolute_overhead_mean_ms"]])

    print(f"\nSaved: {out_path}\nSaved: {out_csv}")


if __name__ == "__main__":
    main()
