#!/usr/bin/env python3
"""Generate the stratified admission-control corpus for Phase 2.

Deterministic (no randomness) so the corpus is byte-identical across runs,
which matters for reproducibility claims. YAML is emitted via string
templates rather than a YAML library, since every value here is a simple
identifier/number we control ourselves.

Constraint isolation (see policies/gatekeeper/constraints/*.yaml):
  - K8sNoPrivileged, K8sNoHostPath, K8sNoRunAsRoot, K8sNoHostNetwork,
    K8sApprovedImages all match kind=Pod in the cde-payments namespace
    SIMULTANEOUSLY. Every Pod manifest here is therefore constructed to
    violate at most one of these five dimensions, and to be clean on the
    other four - otherwise per-category detection/FPR numbers would be
    confounded by unintended cross-violations.
  - K8sTLSIngress matches kind=Ingress; K8sNoWildcardRBAC matches
    kind=Role/ClusterRole. Both are separate resource kinds from Pod, so
    they can't cross-contaminate the Pod-scoped constraints above.

Resource requests are fixed at cpu=10m/memory=16Mi per CLAUDE.md's
cost-discipline rule - never scaled up, regardless of manifest count.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "dataset"
COMPLIANT_DIR = DATASET_DIR / "compliant"
VIOLATIONS_DIR = DATASET_DIR / "violations"
GROUND_TRUTH_CSV = DATASET_DIR / "ground_truth.csv"

NAMESPACE = "cde-payments"
CPU = "10m"
MEM = "16Mi"

APPROVED_IMAGES = [
    "registry.k8s.io/pause:3.9",
    "registry.corp.example/app-service:v1.2.0",
    "gcr.io/trusted/backend-api:v3.0.1",
]
UNAPPROVED_IMAGES = [
    "docker.io/nginx:1.25",
    "nginx:latest",
    "quay.io/someorg/tool:v1",
    "ghcr.io/randomdev/app:latest",
]

ground_truth_rows = []


def _pod_yaml(name, image, *, host_network, privileged, run_as_user, hostpath_volume, labels):
    label_lines = "\n".join(f"    {k}: {v}" for k, v in labels.items())
    volume_mount = ""
    volumes = ""
    if hostpath_volume:
        volume_mount = "\n      volumeMounts:\n        - name: hostvol\n          mountPath: /host"
        volumes = "\n  volumes:\n    - name: hostvol\n      hostPath:\n          path: /etc"
    return f"""apiVersion: v1
kind: Pod
metadata:
  name: {name}
  namespace: {NAMESPACE}
  labels:
{label_lines}
spec:
  hostNetwork: {str(host_network).lower()}
  containers:
    - name: app
      image: {image}
      securityContext:
        privileged: {str(privileged).lower()}
        runAsUser: {run_as_user}{volume_mount}
      resources:
        requests:
          cpu: {CPU}
          memory: {MEM}
        limits:
          cpu: {CPU}
          memory: {MEM}{volumes}
"""


def _ingress_yaml(name, *, tls_block, labels):
    label_lines = "\n".join(f"    {k}: {v}" for k, v in labels.items())
    return f"""apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {name}
  namespace: {NAMESPACE}
  labels:
{label_lines}
spec:{tls_block}
  rules:
    - host: {name}.internal.example
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: backend
                port:
                  number: 80
"""


def _role_yaml(name, *, cluster, rule_resources, rule_verbs, labels):
    kind = "ClusterRole" if cluster else "Role"
    ns_line = "" if cluster else f"  namespace: {NAMESPACE}\n"
    label_lines = "\n".join(f"    {k}: {v}" for k, v in labels.items())
    resources_str = ", ".join(f'"{r}"' for r in rule_resources)
    verbs_str = ", ".join(f'"{v}"' for v in rule_verbs)
    return f"""apiVersion: rbac.authorization.k8s.io/v1
kind: {kind}
metadata:
  name: {name}
{ns_line}  labels:
{label_lines}
rules:
  - apiGroups: [""]
    resources: [{resources_str}]
    verbs: [{verbs_str}]
"""


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def add_row(filename, resource_kind, label, category, subtype, expected_constraint):
    ground_truth_rows.append({
        "filename": filename,
        "resource_kind": resource_kind,
        "label": label,
        "category": category,
        "subtype": subtype,
        "expected_constraint": expected_constraint,
    })


def gen_compliant_pods(n=1800):
    for i in range(n):
        name = f"compliant-pod-{i:04d}"
        image = APPROVED_IMAGES[i % len(APPROVED_IMAGES)]
        content = _pod_yaml(
            name, image,
            host_network=False, privileged=False, run_as_user=1000,
            hostpath_volume=False,
            labels={"dataset": "compliant"},
        )
        rel = f"compliant/{name}.yaml"
        write(COMPLIANT_DIR / f"{name}.yaml", content)
        add_row(rel, "Pod", 0, "none", "none", "")


def gen_compliant_ingress(n=100):
    for i in range(n):
        name = f"compliant-ingress-{i:03d}"
        tls_block = f"""
  tls:
    - hosts:
        - {name}.internal.example
      secretName: {name}-tls"""
        content = _ingress_yaml(name, tls_block=tls_block, labels={"dataset": "compliant"})
        rel = f"compliant/{name}.yaml"
        write(COMPLIANT_DIR / f"{name}.yaml", content)
        add_row(rel, "Ingress", 0, "none", "none", "")


def gen_compliant_rbac(n=100):
    for i in range(n):
        cluster = (i % 2 == 1)
        name = f"compliant-role-{i:03d}"
        content = _role_yaml(
            name, cluster=cluster,
            rule_resources=["pods", "configmaps"], rule_verbs=["get", "list", "watch"],
            labels={"dataset": "compliant"},
        )
        rel = f"compliant/{name}.yaml"
        write(COMPLIANT_DIR / f"{name}.yaml", content)
        add_row(rel, "ClusterRole" if cluster else "Role", 0, "none", "none", "")


def gen_violations_network(n=40):
    for i in range(n):
        name = f"viol-network-{i:03d}"
        image = APPROVED_IMAGES[i % len(APPROVED_IMAGES)]
        content = _pod_yaml(
            name, image,
            host_network=True, privileged=False, run_as_user=1000,
            hostpath_volume=False,
            labels={"dataset": "violation", "category": "network"},
        )
        rel = f"violations/network/{name}.yaml"
        write(VIOLATIONS_DIR / "network" / f"{name}.yaml", content)
        add_row(rel, "Pod", 1, "network", "host_network", "K8sNoHostNetwork")


def gen_violations_secconfig(n=40):
    subtypes = ["privileged", "hostpath", "run_as_root"]
    for i in range(n):
        subtype = subtypes[i % 3]
        name = f"viol-secconfig-{subtype.replace('_', '-')}-{i:03d}"
        image = APPROVED_IMAGES[i % len(APPROVED_IMAGES)]
        if subtype == "privileged":
            content = _pod_yaml(
                name, image, host_network=False, privileged=True, run_as_user=1000,
                hostpath_volume=False, labels={"dataset": "violation", "category": "secconfig", "subtype": subtype},
            )
            expected = "K8sNoPrivileged"
        elif subtype == "hostpath":
            content = _pod_yaml(
                name, image, host_network=False, privileged=False, run_as_user=1000,
                hostpath_volume=True, labels={"dataset": "violation", "category": "secconfig", "subtype": subtype},
            )
            expected = "K8sNoHostPath"
        else:
            content = _pod_yaml(
                name, image, host_network=False, privileged=False, run_as_user=0,
                hostpath_volume=False, labels={"dataset": "violation", "category": "secconfig", "subtype": subtype},
            )
            expected = "K8sNoRunAsRoot"
        rel = f"violations/secconfig/{name}.yaml"
        write(VIOLATIONS_DIR / "secconfig" / f"{name}.yaml", content)
        add_row(rel, "Pod", 1, "secconfig", subtype, expected)


def gen_violations_images(n=40):
    for i in range(n):
        name = f"viol-images-{i:03d}"
        image = UNAPPROVED_IMAGES[i % len(UNAPPROVED_IMAGES)]
        content = _pod_yaml(
            name, image,
            host_network=False, privileged=False, run_as_user=1000,
            hostpath_volume=False,
            labels={"dataset": "violation", "category": "images"},
        )
        rel = f"violations/images/{name}.yaml"
        write(VIOLATIONS_DIR / "images" / f"{name}.yaml", content)
        add_row(rel, "Pod", 1, "images", "unapproved_registry", "K8sApprovedImages")


def gen_violations_tls(n=40):
    for i in range(n):
        subtype = "missing_tls" if i % 2 == 0 else "tls_no_secret"
        name = f"viol-tls-{subtype.replace('_', '-')}-{i:03d}"
        if subtype == "missing_tls":
            tls_block = ""
        else:
            tls_block = f"""
  tls:
    - hosts:
        - {name}.internal.example"""
        content = _ingress_yaml(name, tls_block=tls_block, labels={"dataset": "violation", "category": "tls", "subtype": subtype})
        rel = f"violations/tls/{name}.yaml"
        write(VIOLATIONS_DIR / "tls" / f"{name}.yaml", content)
        add_row(rel, "Ingress", 1, "tls", subtype, "K8sTLSIngress")


def gen_violations_rbac(n=40):
    for i in range(n):
        subtype = "wildcard_resources" if i % 2 == 0 else "wildcard_verbs"
        cluster = (i % 4 >= 2)
        name = f"viol-rbac-{subtype.replace('_', '-')}-{i:03d}"
        if subtype == "wildcard_resources":
            content = _role_yaml(
                name, cluster=cluster, rule_resources=["*"], rule_verbs=["get", "list"],
                labels={"dataset": "violation", "category": "rbac", "subtype": subtype},
            )
        else:
            content = _role_yaml(
                name, cluster=cluster, rule_resources=["pods"], rule_verbs=["*"],
                labels={"dataset": "violation", "category": "rbac", "subtype": subtype},
            )
        rel = f"violations/rbac/{name}.yaml"
        write(VIOLATIONS_DIR / "rbac" / f"{name}.yaml", content)
        add_row(rel, "ClusterRole" if cluster else "Role", 1, "rbac", subtype, "K8sNoWildcardRBAC")


def main():
    gen_compliant_pods(1800)
    gen_compliant_ingress(100)
    gen_compliant_rbac(100)
    gen_violations_network(40)
    gen_violations_secconfig(40)
    gen_violations_images(40)
    gen_violations_tls(40)
    gen_violations_rbac(40)

    GROUND_TRUTH_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(GROUND_TRUTH_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "resource_kind", "label", "category", "subtype", "expected_constraint"])
        writer.writeheader()
        writer.writerows(ground_truth_rows)

    n_compliant = sum(1 for r in ground_truth_rows if r["label"] == 0)
    n_violation = sum(1 for r in ground_truth_rows if r["label"] == 1)
    print(f"Generated {len(ground_truth_rows)} manifests: {n_compliant} compliant, {n_violation} violations")
    print(f"Ground truth: {GROUND_TRUTH_CSV}")


if __name__ == "__main__":
    main()
