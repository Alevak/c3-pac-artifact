#!/usr/bin/env python3
"""Task A.4 - Failure-injection test for the scoped fail-closed config.

Scales gatekeeper-controller-manager to 0 replicas, then verifies:
  1. CDE namespace: object creation FAILS (fail-closed actually blocks
     when the policy engine is unavailable, rather than silently admitting).
  2. kube-system: object creation still SUCCEEDS (the namespaceSelector
     scoping actually limits blast radius - no cluster-wide deadlock).
Measures time from scale-to-0 command to first observed failure. Restores
replicas immediately after, and confirms normal operation resumes before
declaring done.

Kept deliberately short - polls aggressively rather than sleeping long, to
minimize how long the CDE namespace is actually unenforced/blocked.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ENV = os.environ.copy()
ENV["AWS_PROFILE"] = "claude-code"

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DEPLOY = "gatekeeper-controller-manager"
NS = "gatekeeper-system"
CDE_NS = "cde-payments"

log = []


def record(step, detail):
    entry = {"t": datetime.now(timezone.utc).isoformat(), "step": step, "detail": detail}
    log.append(entry)
    print(f"[{entry['t']}] {step}: {detail}")


def kubectl(*args, check=False):
    return subprocess.run(["kubectl", *args], capture_output=True, text=True, env=ENV, check=check)


def try_create_cde_pod(name):
    manifest = f"""apiVersion: v1
kind: Pod
metadata:
  name: {name}
  namespace: {CDE_NS}
spec:
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext: {{privileged: false, runAsUser: 1000}}
      resources: {{requests: {{cpu: 10m, memory: 16Mi}}, limits: {{cpu: 10m, memory: 16Mi}}}}
"""
    path = Path(f"/tmp/{name}.yaml")
    path.write_text(manifest)
    r = kubectl("apply", "--dry-run=server", "-f", str(path))
    path.unlink(missing_ok=True)
    return r.returncode == 0, r.stderr.strip()


def try_create_kubesystem_cm(name):
    r = kubectl("create", "configmap", name, "-n", "kube-system", "--from-literal=x=1", "--dry-run=server")
    return r.returncode == 0, r.stderr.strip()


def main():
    record("start", "Reading current replica count before touching anything")
    r = kubectl("get", "deploy", DEPLOY, "-n", NS, "-o", "jsonpath={.spec.replicas}")
    original_replicas = int(r.stdout.strip())
    record("original_state", f"{DEPLOY} currently at {original_replicas} replicas")

    try:
        record("baseline_check", "Confirming CDE create works normally BEFORE scaling down")
        ok, err = try_create_cde_pod("failinj-baseline")
        record("baseline_cde_create", f"success={ok}")
        assert ok, f"Baseline failed before we even started - aborting. stderr: {err}"

        t_scale = time.time()
        record("scale_to_zero", f"kubectl scale deploy/{DEPLOY} --replicas=0")
        kubectl("scale", "deployment", DEPLOY, "-n", NS, "--replicas=0", check=True)

        record("poll_cde_start", "Polling CDE namespace create every 1s until it fails (fail-closed engaging)")
        t_first_failure = None
        cde_attempts = []
        for i in range(60):  # up to 60s of polling
            ok, err = try_create_cde_pod(f"failinj-cde-probe-{i}")
            elapsed = time.time() - t_scale
            cde_attempts.append({"attempt": i, "elapsed_s": round(elapsed, 2), "admitted": ok,
                                   "error_snippet": err[:200] if not ok else None})
            if not ok:
                t_first_failure = time.time()
                record("cde_first_failure", f"CDE create FAILED after {elapsed:.2f}s (fail-closed engaged). Error: {err[:300]}")
                break
            time.sleep(1)
        else:
            record("cde_never_failed", "WARNING: CDE create never failed within 60s poll window - fail-closed may not be engaging as expected")

        record("kubesystem_check", "Testing kube-system create WHILE gatekeeper is still at 0 replicas (scoping should protect this)")
        ks_ok, ks_err = try_create_kubesystem_cm("failinj-kubesystem-probe")
        record("kubesystem_result", f"success={ks_ok}" + (f", error={ks_err[:300]}" if not ks_ok else ""))

        time_to_first_failure_s = (t_first_failure - t_scale) if t_first_failure else None

    finally:
        record("restore_start", f"Restoring {DEPLOY} to {original_replicas} replicas")
        kubectl("scale", "deployment", DEPLOY, "-n", NS, f"--replicas={original_replicas}", check=True)

        record("wait_ready", "Polling for replicas to become Ready")
        for i in range(60):
            r = kubectl("get", "deploy", DEPLOY, "-n", NS, "-o", "jsonpath={.status.readyReplicas}")
            ready = r.stdout.strip()
            if ready == str(original_replicas):
                record("replicas_ready", f"{ready}/{original_replicas} ready after {i+1}s")
                break
            time.sleep(1)
        else:
            record("replicas_not_ready", f"WARNING: did not reach {original_replicas} ready replicas within 60s")

        record("recovery_check_deny", "Confirming enforcement resumed: privileged pod should be denied again")
        r = kubectl("run", "failinj-recovery-deny", "--image=registry.k8s.io/pause:3.9", "-n", CDE_NS,
                     "--overrides={\"spec\":{\"containers\":[{\"name\":\"failinj-recovery-deny\",\"image\":\"registry.k8s.io/pause:3.9\",\"securityContext\":{\"privileged\":true}}]}}",
                     "--dry-run=server")
        recovery_deny_ok = r.returncode != 0 and "admission webhook" in r.stderr
        record("recovery_deny_result", f"correctly_denied={recovery_deny_ok}")

        record("recovery_check_allow", "Confirming compliant pod still admitted")
        ok, err = try_create_cde_pod("failinj-recovery-allow")
        record("recovery_allow_result", f"admitted={ok}")

    summary = {
        "original_replicas": original_replicas,
        "time_to_first_failure_seconds": round(time_to_first_failure_s, 2) if time_to_first_failure_s else None,
        "cde_probe_attempts": cde_attempts,
        "kube_system_probe_during_outage": {"admitted": ks_ok, "error": ks_err if not ks_ok else None},
        "recovery_confirmed": {
            "enforcement_deny_works": recovery_deny_ok,
            "enforcement_allow_works": ok,
        },
        "step_log": log,
    }
    out_path = RESULTS_DIR / "phase4b_failure_injection.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved: {out_path}")
    print(f"\n=== SUMMARY ===")
    print(f"Time to first fail-closed failure: {summary['time_to_first_failure_seconds']}s")
    print(f"kube-system unaffected during outage: {ks_ok}")
    print(f"Recovery confirmed: deny={recovery_deny_ok}, allow={ok}")


if __name__ == "__main__":
    main()
