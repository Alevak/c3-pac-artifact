#!/usr/bin/env python3
"""Adversarial/edge-case supplement to Phase 3.

The main corpus (dataset/) tests whether Gatekeeper enforces each Rego
rule's LITERAL predicate at scale - it does, perfectly, because the
violations were constructed as direct instances of those exact predicates.
This supplement instead asks: does the policy generalize to semantically
equivalent bypasses the literal Rego wording doesn't happen to cover?

Kept in a separate directory/CSV from dataset/ground_truth.csv on purpose -
this tests a different hypothesis (policy completeness) than Phase 3's
enforcement-at-scale measurement, and conflating the two would muddy what
each number actually claims.

`expected_label` is the ground truth per the CONTROL'S INTENT (PCI-DSS/
NIS2 goal), not per the current Rego's literal wording - that gap is
exactly what this is measuring. `hypothesis` documents the specific
mechanism each case is expected to exploit or confirm.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# NOTE: relocated for the reproducibility artifact - this script now lives in
# dataset/ (alongside generate_dataset.py) instead of scripts/, so its output
# goes into dataset/adversarial/ rather than a separate top-level directory.
OUT_DIR = ROOT / "dataset" / "adversarial"
GROUND_TRUTH_CSV = ROOT / "dataset" / "ground_truth_adversarial.csv"
NAMESPACE = "cde-payments"
CPU, MEM = "10m", "16Mi"

rows = []

# NOTE: the write() calls below run at module level (before main()), so the
# output directory has to exist before any of them fire - this was latent
# and untested until this artifact was verified against a clean checkout
# (the original dev environment happened to already have the directory
# from an earlier run, which masked it).
OUT_DIR.mkdir(parents=True, exist_ok=True)


def write(name, content):
    (OUT_DIR / f"{name}.yaml").write_text(content)


def add(name, resource_kind, category, expected_label, hypothesis):
    rows.append({
        "filename": f"{name}.yaml", "resource_kind": resource_kind,
        "category": category, "expected_label": expected_label, "hypothesis": hypothesis,
    })


# ---------- network ----------
write("adv-network-hostport", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-network-hostport
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: network}}
spec:
  hostNetwork: false
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext: {{privileged: false, runAsUser: 1000}}
      ports:
        - containerPort: 8080
          hostPort: 8080
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-network-hostport", "Pod", "network", 1,
    "hostPort binds to the host's network interface per-container without setting spec.hostNetwork; the current Rego only checks spec.hostNetwork == true.")

write("adv-network-hostpid", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-network-hostpid
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: network}}
spec:
  hostNetwork: false
  hostPID: true
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext: {{privileged: false, runAsUser: 1000}}
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-network-hostpid", "Pod", "network", 1,
    "hostPID:true shares the host's process namespace - a real host-isolation escape in the same family as hostNetwork, but a different field the current constraint never inspects.")

write("adv-network-hostipc", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-network-hostipc
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: network}}
spec:
  hostNetwork: false
  hostIPC: true
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext: {{privileged: false, runAsUser: 1000}}
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-network-hostipc", "Pod", "network", 1,
    "hostIPC:true shares the host's IPC namespace - same host-isolation gap class as hostPID, uninspected field.")

write("adv-network-omitted-compliant", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-network-omitted-compliant
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: network}}
spec:
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext: {{privileged: false, runAsUser: 1000}}
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-network-omitted-compliant", "Pod", "network", 0,
    "Sanity true-negative: hostNetwork field omitted entirely (not explicit false) should still be treated as compliant - confirms the default/undefined case doesn't false-positive.")

# ---------- secconfig ----------
write("adv-secconfig-allowprivesc", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-secconfig-allowprivesc
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: secconfig}}
spec:
  hostNetwork: false
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext:
        privileged: false
        runAsUser: 1000
        allowPrivilegeEscalation: true
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-secconfig-allowprivesc", "Pod", "secconfig", 1,
    "allowPrivilegeEscalation:true lets a process gain more privileges than its parent without privileged:true - an escalation vector the current Rego (privileged-only) never checks.")

write("adv-secconfig-capabilities", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-secconfig-capabilities
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: secconfig}}
spec:
  hostNetwork: false
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext:
        privileged: false
        runAsUser: 1000
        capabilities:
          add: ["SYS_ADMIN"]
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-secconfig-capabilities", "Pod", "secconfig", 1,
    "capabilities.add:[SYS_ADMIN] grants near-privileged access without privileged:true - Rego only checks the privileged boolean, never the capabilities list.")

write("adv-secconfig-implicit-root", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-secconfig-implicit-root
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: secconfig}}
spec:
  hostNetwork: false
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext:
        privileged: false
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-secconfig-implicit-root", "Pod", "secconfig", 1,
    "runAsUser omitted entirely - many base images default to UID 0. Rego only flags EXPLICIT runAsUser==0, not the (arguably more common) implicit-root case.")

write("adv-secconfig-podlevel-root", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-secconfig-podlevel-root
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: secconfig}}
spec:
  hostNetwork: false
  securityContext:
    runAsUser: 0
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext:
        privileged: false
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-secconfig-podlevel-root", "Pod", "secconfig", 1,
    "runAsUser:0 set at spec.securityContext (pod-level, inherited by containers) rather than spec.containers[].securityContext - Rego's c.securityContext.runAsUser only inspects the container-level field.")

write("adv-secconfig-hardened-compliant", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-secconfig-hardened-compliant
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: secconfig}}
spec:
  hostNetwork: false
  containers:
    - name: app
      image: registry.k8s.io/pause:3.9
      securityContext:
        privileged: false
        runAsUser: 1000
        runAsNonRoot: true
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-secconfig-hardened-compliant", "Pod", "secconfig", 0,
    "Sanity true-negative: explicitly hardened pod (allowPrivilegeEscalation:false, capabilities dropped) should not be false-flagged.")

# ---------- images ----------
write("adv-images-prefix-bypass-k8sio", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-images-prefix-bypass-k8sio
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: images}}
spec:
  hostNetwork: false
  containers:
    - name: app
      image: registry.k8s.io.evil.example/backdoor:latest
      securityContext: {{privileged: false, runAsUser: 1000}}
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-images-prefix-bypass-k8sio", "Pod", "images", 1,
    "Rego uses startswith(img, reg) - a naive string-prefix check, not a hostname-boundary check. 'registry.k8s.io.evil.example/...' literally starts with the approved string 'registry.k8s.io'.")

write("adv-images-prefix-bypass-gcr", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-images-prefix-bypass-gcr
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: images}}
spec:
  hostNetwork: false
  containers:
    - name: app
      image: gcr.io/trusted-malicious/backdoor:latest
      securityContext: {{privileged: false, runAsUser: 1000}}
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-images-prefix-bypass-gcr", "Pod", "images", 1,
    "Same startswith prefix bug: 'gcr.io/trusted-malicious/...' starts with the approved string 'gcr.io/trusted' even though it is a different, untrusted path.")

write("adv-images-legit-complex-tag-compliant", f"""apiVersion: v1
kind: Pod
metadata:
  name: adv-images-legit-complex-tag-compliant
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: images}}
spec:
  hostNetwork: false
  containers:
    - name: app
      image: "gcr.io/trusted/app@sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
      securityContext: {{privileged: false, runAsUser: 1000}}
      resources:
        requests: {{cpu: {CPU}, memory: {MEM}}}
        limits: {{cpu: {CPU}, memory: {MEM}}}
""")
add("adv-images-legit-complex-tag-compliant", "Pod", "images", 0,
    "Sanity true-negative: genuinely approved registry with a digest-pinned reference should not false-positive on unusual-looking (but legitimate) tag syntax.")

# ---------- tls ----------
write("adv-tls-empty-secretname", f"""apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: adv-tls-empty-secretname
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: tls}}
spec:
  tls:
    - hosts: ["adv-tls-empty-secretname.internal.example"]
      secretName: ""
  rules:
    - host: adv-tls-empty-secretname.internal.example
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: {{name: backend, port: {{number: 80}}}}
""")
add("adv-tls-empty-secretname", "Ingress", "tls", 1,
    "secretName is present but empty (\"\"). Rego's `tls[_].secretName` only checks the field is DEFINED, not non-empty - an empty string still satisfies a bare reference in Rego.")

write("adv-tls-partial-multihost", f"""apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: adv-tls-partial-multihost
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: tls}}
spec:
  tls:
    - hosts: ["adv-tls-partial-multihost-a.internal.example"]
      secretName: adv-tls-partial-multihost-a-tls
    - hosts: ["adv-tls-partial-multihost-b.internal.example"]
  rules:
    - host: adv-tls-partial-multihost-a.internal.example
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: {{name: backend, port: {{number: 80}}}}
    - host: adv-tls-partial-multihost-b.internal.example
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: {{name: backend, port: {{number: 80}}}}
""")
add("adv-tls-partial-multihost", "Ingress", "tls", 1,
    "Two tls[] entries, only the first has secretName. Rego's tls[_].secretName is existential (\"at least one\"), so the second host's missing TLS is invisible to the check.")

write("adv-tls-multihost-compliant", f"""apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: adv-tls-multihost-compliant
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: tls}}
spec:
  tls:
    - hosts: ["adv-tls-multihost-compliant-a.internal.example"]
      secretName: adv-tls-multihost-compliant-a-tls
    - hosts: ["adv-tls-multihost-compliant-b.internal.example"]
      secretName: adv-tls-multihost-compliant-b-tls
  rules:
    - host: adv-tls-multihost-compliant-a.internal.example
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: {{name: backend, port: {{number: 80}}}}
    - host: adv-tls-multihost-compliant-b.internal.example
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: {{name: backend, port: {{number: 80}}}}
""")
add("adv-tls-multihost-compliant", "Ingress", "tls", 0,
    "Sanity true-negative: both hosts properly TLS-configured should not false-positive.")

# ---------- rbac ----------
write("adv-rbac-clusteradmin-binding", f"""apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: adv-rbac-clusteradmin-binding
  labels: {{dataset: adversarial, category: rbac}}
subjects:
  - kind: ServiceAccount
    name: some-workload-sa
    namespace: {NAMESPACE}
roleRef:
  kind: ClusterRole
  name: cluster-admin
  apiGroup: rbac.authorization.k8s.io
""")
add("adv-rbac-clusteradmin-binding", "ClusterRoleBinding", "rbac", 1,
    "Binds a subject to the built-in cluster-admin ClusterRole (full wildcard access) WITHOUT creating any new Role/ClusterRole object. K8sNoWildcardRBAC only matches kind=Role/ClusterRole, so this entire escalation path is invisible to the constraint.")

write("adv-rbac-enumerated-near-wildcard", f"""apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: adv-rbac-enumerated-near-wildcard
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: rbac}}
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "configmaps", "secrets", "endpoints", "persistentvolumeclaims", "events", "serviceaccounts", "replicationcontrollers", "namespaces", "nodes", "podtemplates", "limitranges", "resourcequotas", "bindings"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
""")
add("adv-rbac-enumerated-near-wildcard", "Role", "rbac", 1,
    "Every core-group resource type is enumerated explicitly instead of using \"*\" - functionally near-equivalent to wildcard access, but the literal string-equality check (rule.resources[_] == \"*\") never matches.")

write("adv-rbac-apigroup-wildcard", f"""apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: adv-rbac-apigroup-wildcard
  namespace: {NAMESPACE}
  labels: {{dataset: adversarial, category: rbac}}
rules:
  - apiGroups: ["*"]
    resources: ["deployments"]
    verbs: ["get", "list"]
""")
add("adv-rbac-apigroup-wildcard", "Role", "rbac", 1,
    "apiGroups:[\"*\"] grants access to the 'deployments' resource across every API group. The Rego rule never inspects apiGroups at all, only resources and verbs.")


def main():
    OUT_DIR.mkdir(exist_ok=True)
    with open(GROUND_TRUTH_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "resource_kind", "category", "expected_label", "hypothesis"])
        w.writeheader()
        w.writerows(rows)
    n1 = sum(1 for r in rows if r["expected_label"] == 1)
    n0 = sum(1 for r in rows if r["expected_label"] == 0)
    print(f"Generated {len(rows)} adversarial manifests: {n1} expected-should-be-denied, {n0} sanity true-negatives")
    print(f"Ground truth: {GROUND_TRUTH_CSV}")


if __name__ == "__main__":
    main()
