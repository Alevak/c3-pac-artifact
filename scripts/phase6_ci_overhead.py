#!/usr/bin/env python3
"""Phase 6 - CI overhead (OVER): Conftest execution time vs a no-policy baseline.

Baseline = the SAME conftest binary, same invocation shape, pointed at an
EMPTY policy directory. This isolates conftest's own fixed cost (process
startup, YAML/JSON parsing, Rego runtime init) from the cost the actual
policy rules add - a cleaner apples-to-apples comparison than timing an
unrelated external tool.

Batch sizes simulate realistic CI trigger scenarios: a single-file PR, a
small multi-file PR, a larger batch deploy, and a full-repo compliance
sweep. Each batch is passed to ONE conftest invocation (not one process per
file), matching how a real CI step would actually be written.

Policies used: policies/conftest/ (the adapted req*.rego set - see Phase 6
report for two documented, carried-over limitations: req7 only checks
kind==ClusterRole, not Role, and req1/req10 test controls this corpus
wasn't designed to satisfy). Both are inherited from the original policy
library, not introduced by the input-shape adaptation done for this phase.
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
EMPTY_POLICY_DIR = ROOT / "policies" / "conftest_empty"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

BATCH_SIZES_AND_REPEATS = [
    (1, 15),
    (10, 15),
    (100, 10),
    (500, 10),
    (2200, 8),
]


def stratified_sample(rows, n):
    if n >= len(rows):
        return rows
    step = len(rows) / n
    return [rows[int(i * step) % len(rows)] for i in range(n)]


def time_conftest_run(files, policy_dir):
    file_args = [str(DATASET_DIR / f) for f in files]
    t0 = time.perf_counter()
    subprocess.run(
        ["conftest", "test", *file_args, "-p", str(policy_dir), "--all-namespaces", "-o", "json"],
        capture_output=True, text=True,
    )
    return (time.perf_counter() - t0) * 1000  # ms


def mean_p95(values):
    s = sorted(values)
    return {
        "mean_ms": round(statistics.mean(s), 1),
        "p95_ms": round(s[int(len(s) * 0.95)] if len(s) > 1 else s[0], 1),
        "min_ms": round(min(s), 1),
        "max_ms": round(max(s), 1),
        "n": len(s),
    }


def main():
    with open(GROUND_TRUTH_CSV) as f:
        rows = list(csv.DictReader(f))

    results = []
    for n_files, repeats in BATCH_SIZES_AND_REPEATS:
        sample = stratified_sample(rows, n_files)
        filenames = [r["filename"] for r in sample]
        print(f"\n=== Batch size {n_files} files, {repeats} repeats ===")

        baseline_times = [time_conftest_run(filenames, EMPTY_POLICY_DIR) for _ in range(repeats)]
        real_times = [time_conftest_run(filenames, REAL_POLICY_DIR) for _ in range(repeats)]

        b_stats = mean_p95(baseline_times)
        r_stats = mean_p95(real_times)
        overhead_mean_ms = r_stats["mean_ms"] - b_stats["mean_ms"]
        overhead_p95_ms = r_stats["p95_ms"] - b_stats["p95_ms"]
        rel_overhead_mean_pct = (overhead_mean_ms / b_stats["mean_ms"] * 100) if b_stats["mean_ms"] else None
        rel_overhead_p95_pct = (overhead_p95_ms / b_stats["p95_ms"] * 100) if b_stats["p95_ms"] else None

        row = {
            "batch_size": n_files, "repeats": repeats,
            "baseline": b_stats, "real_policy": r_stats,
            "overhead_mean_ms": round(overhead_mean_ms, 1),
            "overhead_p95_ms": round(overhead_p95_ms, 1),
            "relative_overhead_mean_pct": round(rel_overhead_mean_pct, 1) if rel_overhead_mean_pct is not None else None,
            "relative_overhead_p95_pct": round(rel_overhead_p95_pct, 1) if rel_overhead_p95_pct is not None else None,
        }
        results.append(row)
        print(json.dumps(row, indent=2))

    out_json = RESULTS_DIR / "phase6_ci_overhead.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)

    out_csv = RESULTS_DIR / "phase6_ci_overhead.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["batch_size", "repeats", "baseline_mean_ms", "baseline_p95_ms",
                     "real_mean_ms", "real_p95_ms", "overhead_mean_ms", "overhead_p95_ms",
                     "relative_overhead_mean_pct", "relative_overhead_p95_pct"])
        for r in results:
            w.writerow([r["batch_size"], r["repeats"], r["baseline"]["mean_ms"], r["baseline"]["p95_ms"],
                         r["real_policy"]["mean_ms"], r["real_policy"]["p95_ms"],
                         r["overhead_mean_ms"], r["overhead_p95_ms"],
                         r["relative_overhead_mean_pct"], r["relative_overhead_p95_pct"]])

    print(f"\nSaved: {out_json}\nSaved: {out_csv}")


if __name__ == "__main__":
    main()
