#!/usr/bin/env python3
"""Phase 4 - Admission latency under concurrent load.

Measures the actual webhook processing time by scraping Gatekeeper's own
Prometheus histogram (gatekeeper_validation_request_duration_seconds)
before/after each load tier, rather than timing `kubectl` round-trips -
kubectl process-spawn and network RTT would dominate and mask the number
we actually care about (what the policy engine itself adds to a request).

No monitoring stack is deployed for this - a single `kubectl port-forward`
to the existing gatekeeper-controller-manager pod's own /metrics endpoint
is enough to scrape the histogram directly.

Three concurrency tiers are run as separate, delineated measurements
(serial baseline, then two "under load" levels) so we can see whether
latency actually degrades as concurrency increases, not just report one
number and call it "under load".
"""
import csv
import json
import os
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "dataset"
GROUND_TRUTH_CSV = DATASET_DIR / "ground_truth.csv"
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

ENV = os.environ.copy()
ENV["AWS_PROFILE"] = "claude-code"

METRICS_PORT = 18889
METRICS_URL = f"http://localhost:{METRICS_PORT}/metrics"

TIERS = [
    {"name": "serial_baseline", "concurrency": 1, "n": 150},
    {"name": "concurrent_10", "concurrency": 10, "n": 300},
    {"name": "concurrent_30", "concurrency": 30, "n": 300},
]


def get_replica_pod_names():
    out = subprocess.run(
        ["kubectl", "get", "pods", "-n", "gatekeeper-system",
         "-l", "control-plane=controller-manager", "-o", "jsonpath={.items[*].metadata.name}"],
        capture_output=True, text=True, env=ENV, check=True,
    )
    return out.stdout.split()


def start_port_forwards(pod_names):
    """One port-forward per replica pod, on its own local port. Admission
    traffic is load-balanced across all replicas by the Service, so we
    have to scrape every replica individually and sum - port-forwarding
    to `deploy/...` only reaches one arbitrary pod and silently
    undercounts (confirmed: undercount got worse as concurrency, and
    therefore replica spread, increased)."""
    procs = []
    ports = []
    for i, pod in enumerate(pod_names):
        port = METRICS_PORT + i
        proc = subprocess.Popen(
            ["kubectl", "port-forward", "-n", "gatekeeper-system", pod, f"{port}:8888"],
            env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(proc)
        ports.append(port)
    time.sleep(3)
    return procs, ports


def scrape_metrics_one(port):
    url = f"http://localhost:{port}/metrics"
    with urllib.request.urlopen(url, timeout=10) as resp:
        text = resp.read().decode()
    buckets = {}  # status -> {le_float: cumulative_count}
    for line in text.splitlines():
        if not line.startswith("gatekeeper_validation_request_duration_seconds_bucket{"):
            continue
        # gatekeeper_validation_request_duration_seconds_bucket{admission_status="allow",le="0.001"} 131
        labels_part, value = line.rsplit("} ", 1)
        labels_part = labels_part.split("{", 1)[1]
        status = None
        le = None
        for kv in labels_part.split(","):
            k, v = kv.split("=", 1)
            v = v.strip('"')
            if k == "admission_status":
                status = v
            elif k == "le":
                le = float("inf") if v == "+Inf" else float(v)
        buckets.setdefault(status, {})[le] = int(value)
    return buckets


def scrape_metrics(ports):
    """Sum bucket counts across every replica's /metrics."""
    combined = {}
    for port in ports:
        b = scrape_metrics_one(port)
        for status, les in b.items():
            combined.setdefault(status, {})
            for le, count in les.items():
                combined[status][le] = combined[status].get(le, 0) + count
    return combined


def diff_buckets(before, after):
    """Delta per status per le. Assumes identical le boundaries (true here)."""
    delta = {}
    for status in after:
        delta[status] = {}
        before_s = before.get(status, {})
        for le, count_after in after[status].items():
            count_before = before_s.get(le, 0)
            delta[status][le] = max(0, count_after - count_before)
    return delta


def merge_statuses(delta):
    """Sum allow+deny bucket counts by le, for a combined view."""
    combined = {}
    for status, buckets in delta.items():
        for le, c in buckets.items():
            combined[le] = combined.get(le, 0) + c
    return combined


def quantile_from_buckets(buckets: dict, q: float):
    """Standard Prometheus histogram_quantile linear interpolation."""
    if not buckets:
        return None
    sorted_les = sorted(buckets.keys())
    total = buckets[sorted_les[-1]]  # cumulative count at +Inf
    if total == 0:
        return None
    target = q * total
    prev_le, prev_count = 0.0, 0
    for le in sorted_les:
        count = buckets[le]
        if count >= target:
            if le == float("inf"):
                return prev_le  # can't interpolate past the last finite bucket
            if count == prev_count:
                return le
            frac = (target - prev_count) / (count - prev_count)
            return prev_le + frac * (le - prev_le)
        prev_le, prev_count = le, count
    return sorted_les[-1] if sorted_les[-1] != float("inf") else prev_le


def stratified_sample(rows, n):
    """Spread n indices evenly across the FULL row list, so the sample
    includes both compliant and violation rows regardless of n. A naive
    `i % len(rows)` for small n only ever hits the front of the list -
    and ground_truth.csv orders all 2000 compliant rows before the 200
    violations, so that would silently sample zero violations."""
    step = len(rows) / n
    return [rows[int(i * step) % len(rows)] for i in range(n)]


def apply_one_instrumented(row):
    path = DATASET_DIR / row["filename"]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            ["kubectl", "apply", "--dry-run=server", "-f", str(path)],
            capture_output=True, text=True, env=ENV, timeout=15,
        )
        client_ms = (time.perf_counter() - t0) * 1000
        stderr = proc.stderr.strip()
        if proc.returncode == 0:
            outcome = "ADMITTED"
        elif "admission webhook" in stderr and "denied" in stderr:
            outcome = "DENIED"
        else:
            outcome = "ERROR"
    except subprocess.TimeoutExpired:
        client_ms = (time.perf_counter() - t0) * 1000
        outcome = "CLIENT_TIMEOUT"
    return {"filename": row["filename"], "outcome": outcome, "client_ms": round(client_ms, 1)}


def run_tier(rows, tier, ports):
    n, concurrency = tier["n"], tier["concurrency"]
    sample = stratified_sample(rows, n)
    n_violations_sampled = sum(1 for r in sample if r["label"] == "1")

    before = scrape_metrics(ports)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        client_results = list(ex.map(apply_one_instrumented, sample))
    wall_time = time.time() - t0
    time.sleep(1)  # let metrics scrape endpoint settle
    after = scrape_metrics(ports)

    delta = diff_buckets(before, after)
    combined = merge_statuses(delta)
    n_hist_observed = combined.get(float("inf"), 0)

    client_admitted = sum(1 for r in client_results if r["outcome"] == "ADMITTED")
    client_denied = sum(1 for r in client_results if r["outcome"] == "DENIED")
    client_error = sum(1 for r in client_results if r["outcome"] == "ERROR")
    client_timeout = sum(1 for r in client_results if r["outcome"] == "CLIENT_TIMEOUT")
    client_ms_sorted = sorted(r["client_ms"] for r in client_results)

    def pctl(sorted_list, q):
        if not sorted_list:
            return None
        idx = min(len(sorted_list) - 1, int(q * len(sorted_list)))
        return round(sorted_list[idx], 1)

    result = {
        "tier": tier["name"], "concurrency": concurrency, "n_requests": n,
        "n_violations_sampled": n_violations_sampled,
        "wall_time_seconds": round(wall_time, 2),
        "throughput_req_per_sec": round(n / wall_time, 1) if wall_time > 0 else None,
        "client_observed": {
            "admitted": client_admitted, "denied": client_denied,
            "error": client_error, "timeout": client_timeout,
            "p50_ms": pctl(client_ms_sorted, 0.50),
            "p95_ms": pctl(client_ms_sorted, 0.95),
            "p99_ms": pctl(client_ms_sorted, 0.99),
        },
        "webhook_histogram": {
            "n_observed": n_hist_observed,
            "n_expected": n,
            "discrepancy": n_hist_observed - n,
            "p50_ms": round(quantile_from_buckets(combined, 0.50) * 1000, 3) if quantile_from_buckets(combined, 0.50) is not None else None,
            "p95_ms": round(quantile_from_buckets(combined, 0.95) * 1000, 3) if quantile_from_buckets(combined, 0.95) is not None else None,
            "p99_ms": round(quantile_from_buckets(combined, 0.99) * 1000, 3) if quantile_from_buckets(combined, 0.99) is not None else None,
        },
    }
    for status in ("allow", "deny"):
        b = delta.get(status, {})
        n_obs = b.get(float("inf"), 0)
        result[f"webhook_{status}"] = {
            "n_observed": n_obs,
            "p50_ms": round(quantile_from_buckets(b, 0.50) * 1000, 3) if n_obs and quantile_from_buckets(b, 0.50) is not None else None,
            "p95_ms": round(quantile_from_buckets(b, 0.95) * 1000, 3) if n_obs and quantile_from_buckets(b, 0.95) is not None else None,
            "p99_ms": round(quantile_from_buckets(b, 0.99) * 1000, 3) if n_obs and quantile_from_buckets(b, 0.99) is not None else None,
        }
    return result


def main():
    with open(GROUND_TRUTH_CSV) as f:
        rows = list(csv.DictReader(f))

    pod_names = get_replica_pod_names()
    print(f"Found {len(pod_names)} gatekeeper-controller-manager replicas: {pod_names}")
    print("Starting one port-forward per replica (admission traffic is load-balanced across all of them)...")
    procs, ports = start_port_forwards(pod_names)
    try:
        scrape_metrics(ports)  # sanity check all are reachable
    except Exception as e:
        for p in procs:
            p.terminate()
        raise SystemExit(f"Could not reach metrics endpoint: {e}")

    results = []
    try:
        for tier in TIERS:
            print(f"\n=== Tier: {tier['name']} (concurrency={tier['concurrency']}, n={tier['n']}) ===")
            r = run_tier(rows, tier, ports)
            results.append(r)
            print(json.dumps(r, indent=2))
    finally:
        for p in procs:
            p.terminate()

    out_json = RESULTS_DIR / "phase4_latency.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2)

    out_csv = RESULTS_DIR / "phase4_latency_summary.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tier", "concurrency", "n_requests", "n_violations_sampled", "wall_time_s", "throughput_req_s",
                     "client_admitted", "client_denied", "client_error", "client_timeout",
                     "client_p50_ms", "client_p95_ms", "client_p99_ms",
                     "webhook_n_observed", "webhook_discrepancy",
                     "webhook_p50_ms", "webhook_p95_ms", "webhook_p99_ms",
                     "webhook_allow_p50_ms", "webhook_allow_p95_ms", "webhook_allow_p99_ms",
                     "webhook_deny_p50_ms", "webhook_deny_p95_ms", "webhook_deny_p99_ms"])
        for r in results:
            co, wh = r["client_observed"], r["webhook_histogram"]
            w.writerow([r["tier"], r["concurrency"], r["n_requests"], r["n_violations_sampled"],
                         r["wall_time_seconds"], r["throughput_req_per_sec"],
                         co["admitted"], co["denied"], co["error"], co["timeout"],
                         co["p50_ms"], co["p95_ms"], co["p99_ms"],
                         wh["n_observed"], wh["discrepancy"], wh["p50_ms"], wh["p95_ms"], wh["p99_ms"],
                         r["webhook_allow"]["p50_ms"], r["webhook_allow"]["p95_ms"], r["webhook_allow"]["p99_ms"],
                         r["webhook_deny"]["p50_ms"], r["webhook_deny"]["p95_ms"], r["webhook_deny"]["p99_ms"]])

    print(f"\nSaved: {out_json}")
    print(f"Saved: {out_csv}")


if __name__ == "__main__":
    main()
