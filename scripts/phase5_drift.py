#!/usr/bin/env python3
"""Phase 5 - Drift detection latency.

To genuinely test the AUDIT controller (not just re-test the admission
webhook), a non-compliant object has to get INTO the cluster without being
blocked at creation. The standard way to do that with Gatekeeper: flip one
Constraint's enforcementAction to "dryrun" (admits + logs, doesn't block),
create the violating object, then measure how long the periodic audit loop
takes to surface it in that Constraint's status.violations.

Gatekeeper's audit controller is confirmed running with --audit-interval=60
(checked directly against the live gatekeeper-audit Deployment args) - so
detection latency here is fundamentally bounded by that periodic cycle, not
a continuously-reactive watch. That's an expected, well-understood property
of a periodic-audit architecture and is reported as such, not presented as
if it were instant.

This temporarily weakens enforcement for ONE constraint (K8sNoPrivileged)
for the duration of the test only, and restores it to "deny" immediately
after each trial - including on error, via try/finally.
"""
import csv
import json
import subprocess
import time
from pathlib import Path

import os
ENV = os.environ.copy()
ENV["AWS_PROFILE"] = "claude-code"

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

NAMESPACE = "cde-payments"
CONSTRAINT_KIND = "k8snoprivileged"
CONSTRAINT_NAME = "no-privileged-containers"
N_TRIALS = 3
POLL_INTERVAL_S = 3
MAX_WAIT_S = 150  # 2.5x the 60s audit interval


def kubectl(*args, check=True):
    return subprocess.run(["kubectl", *args], capture_output=True, text=True, env=ENV, check=check)


def set_enforcement_action(action):
    kubectl("patch", CONSTRAINT_KIND, CONSTRAINT_NAME, "--type=merge",
            "-p", json.dumps({"spec": {"enforcementAction": action}}))


def get_enforcement_action():
    r = kubectl("get", CONSTRAINT_KIND, CONSTRAINT_NAME, "-o", "jsonpath={.spec.enforcementAction}")
    return r.stdout.strip()


def drift_pod_yaml(name):
    return f"""apiVersion: v1
kind: Pod
metadata:
  name: {name}
  namespace: {NAMESPACE}
  labels: {{dataset: drift-test}}
spec:
  hostNetwork: false
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext:
        privileged: true
        runAsUser: 1000
      resources:
        requests: {{cpu: 10m, memory: 16Mi}}
        limits: {{cpu: 10m, memory: 16Mi}}
"""


def get_violation_names():
    r = kubectl("get", CONSTRAINT_KIND, CONSTRAINT_NAME, "-o", "jsonpath={.status.violations}", check=False)
    if not r.stdout.strip():
        return []
    try:
        violations = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    return [v.get("name") for v in violations]


def run_trial(trial_num):
    pod_name = f"drift-test-{trial_num}-{int(time.time())}"
    print(f"\n--- Trial {trial_num}: creating {pod_name} (admission is in dryrun for K8sNoPrivileged, should be ADMITTED) ---")

    manifest_path = RESULTS_DIR / f"_tmp_{pod_name}.yaml"
    manifest_path.write_text(drift_pod_yaml(pod_name))

    apply_result = kubectl("apply", "-f", str(manifest_path), check=False)
    if apply_result.returncode != 0:
        manifest_path.unlink(missing_ok=True)
        return {"trial": trial_num, "pod_name": pod_name, "outcome": "ADMISSION_BLOCKED_UNEXPECTEDLY",
                "detail": apply_result.stderr.strip()}
    manifest_path.unlink(missing_ok=True)

    created_at_str = kubectl("get", "pod", pod_name, "-n", NAMESPACE,
                              "-o", "jsonpath={.metadata.creationTimestamp}").stdout.strip()
    t0 = time.time()  # our own wall clock at confirmed-created

    print(f"  created at {created_at_str} (server), t0={t0:.1f} (local). Polling audit status every {POLL_INTERVAL_S}s...")
    detected = False
    t1 = None
    waited = 0
    while waited < MAX_WAIT_S:
        names = get_violation_names()
        if pod_name in names:
            t1 = time.time()
            detected = True
            break
        time.sleep(POLL_INTERVAL_S)
        waited += POLL_INTERVAL_S

    kubectl("delete", "pod", pod_name, "-n", NAMESPACE, "--wait=false", check=False)

    if detected:
        latency_s = t1 - t0
        print(f"  DETECTED after {latency_s:.1f}s")
        return {"trial": trial_num, "pod_name": pod_name, "outcome": "DETECTED",
                "created_at_server": created_at_str, "latency_seconds": round(latency_s, 1)}
    else:
        print(f"  NOT DETECTED within {MAX_WAIT_S}s - timeout")
        return {"trial": trial_num, "pod_name": pod_name, "outcome": "TIMEOUT",
                "created_at_server": created_at_str, "latency_seconds": None}


def main():
    original_action = get_enforcement_action()
    print(f"Current enforcementAction for {CONSTRAINT_NAME}: {original_action}")
    assert original_action == "deny", f"Expected 'deny' before starting, got '{original_action}' - aborting to avoid masking an already-modified state"

    results = []
    try:
        print(f"Setting {CONSTRAINT_NAME} enforcementAction: deny -> dryrun (temporary, for this test only)")
        set_enforcement_action("dryrun")
        time.sleep(2)
        confirmed = get_enforcement_action()
        print(f"Confirmed: {confirmed}")

        for i in range(1, N_TRIALS + 1):
            results.append(run_trial(i))
    finally:
        print(f"\nRestoring {CONSTRAINT_NAME} enforcementAction: dryrun -> deny")
        set_enforcement_action("deny")
        time.sleep(2)
        restored = get_enforcement_action()
        print(f"Confirmed restored: {restored}")
        if restored != "deny":
            print("WARNING: enforcementAction did not restore to 'deny' - manual check needed!")

    out_json = RESULTS_DIR / "phase5_drift.json"
    with open(out_json, "w") as f:
        json.dump({"audit_interval_seconds": 60, "trials": results}, f, indent=2)

    out_csv = RESULTS_DIR / "phase5_drift.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["trial", "pod_name", "outcome", "created_at_server", "latency_seconds"])
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in ["trial", "pod_name", "outcome", "created_at_server", "latency_seconds"]})

    detected = [r["latency_seconds"] for r in results if r["outcome"] == "DETECTED"]
    print(f"\n=== Summary ===")
    print(f"Trials: {len(results)}, detected: {len(detected)}, timeout: {sum(1 for r in results if r['outcome']=='TIMEOUT')}")
    if detected:
        print(f"Latencies (s): {detected}")
        print(f"Median: {sorted(detected)[len(detected)//2]}s")
    print(f"Saved: {out_json}\nSaved: {out_csv}")


if __name__ == "__main__":
    main()
