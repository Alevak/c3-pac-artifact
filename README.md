# C3 — Policy-as-Code Compliance Framework (Reproducibility Artifact)

This repository is the reproducibility artifact for the paper **"Policy-as-
Code Compliance Framework for PCI DSS and NIS2 in Kubernetes Environments
(C3)"** (Computers & Security, manuscript COSE-D-26-03044). It contains
everything needed to re-run the production-representative EKS validation
described in the paper: the Terraform infrastructure definition, the OPA
Gatekeeper and Conftest policy libraries (Rego), the synthetic dataset
generator, the evaluation scripts for every experimental phase, and the raw
measurement output those scripts produced.

The core idea validated here: enforcing PCI DSS / NIS2 controls in a
Kubernetes cluster as versioned, testable Rego policy — evaluated both at
live admission time (OPA Gatekeeper) and statically in CI (Conftest) — and
measuring detection accuracy, admission latency, drift-detection latency,
and CI overhead at a scale (2,200 synthetic manifests) beyond the smaller
Kind-based validation in prior work.

## Repository layout

```
terraform/          EKS cluster definition (*.tf) + tfvars.EXAMPLE template
policies/
  gatekeeper/        7 ConstraintTemplates + Constraints (live admission control)
  conftest/          Same 7 controls adapted for static/CI evaluation
dataset/
  generate_dataset.py              deterministic generator: 2,200-manifest corpus
  generate_adversarial_dataset.py  18-manifest adversarial/edge-case supplement
  ground_truth.csv                 labels for the main corpus
  ground_truth_adversarial.csv     labels + hypothesis for the adversarial set
scripts/             one script per experimental phase (see mapping below)
results/             raw JSON/CSV output from every phase - the actual paper data
requirements.txt     Python deps (none - stdlib only, see the file)
ENVIRONMENT.md        tool versions used
SANITIZATION_REPORT.md  what was scrubbed from this artifact and why
RELEASE_CHECKLIST.md    manual steps for the maintainer to publish this repo
```

## Prerequisites

See `ENVIRONMENT.md` for exact versions. In brief: Terraform ≥1.6 (tested
on 1.15.8), `kubectl` ≥1.30, `conftest` (tested on 0.59.0), `helm`, an AWS
account with permission to create a VPC/EKS cluster/IAM resources, and
Python 3.10+ (no third-party packages required).

### Cost warning

Provisioning the EKS cluster in `terraform/` costs real money: roughly
**$0.25/hour** (EKS control plane $0.10/h + 3× spot `m5.large` nodes
~$0.11/h + EBS ~$0.01/h). A full reproduction run (provision → all phases →
export) takes on the order of an hour; leaving the cluster up overnight
costs a few dollars, not tens. **Run `terraform destroy` when you're done** —
nothing in this repository does that for you automatically, and forgetting
it is the most common way this kind of experiment generates a surprise
bill. The Terraform config includes AWS Budget alerts (50/80/100% of a
configurable monthly limit) as a safety net, not a substitute for
destroying the cluster.

## Step-by-step reproduction

1. **Provision.**
   ```bash
   cd terraform
   cp terraform.tfvars.EXAMPLE terraform.tfvars   # fill in your email + public IP
   terraform init
   terraform plan   # review before applying anything that costs money
   terraform apply
   ```
2. **Configure `kubectl`** against the new cluster (Terraform prints the
   exact command as an output — `terraform output kubeconfig_command`).
3. **Deploy the policy layer.**
   ```bash
   helm repo add gatekeeper https://open-policy-agent.github.io/gatekeeper/charts
   helm install gatekeeper gatekeeper/gatekeeper --version 3.23.0 \
     --namespace gatekeeper-system --create-namespace --wait
   kubectl apply -f ../policies/gatekeeper/templates/
   kubectl apply -f ../policies/gatekeeper/constraints/
   kubectl create namespace cde-payments
   kubectl label namespace cde-payments pci-cde=true
   kubectl apply -f ../policies/gatekeeper/default-deny-netpol.yaml
   ```
4. **Generate the dataset** (fully offline, no cluster needed):
   ```bash
   cd ../dataset
   python3 generate_dataset.py
   python3 generate_adversarial_dataset.py
   ```
5. **Run the phases**, from `scripts/`:
   - `phase3_admission_eval.py` — main corpus admission evaluation (Phase 3)
   - `evaluate_adversarial.py` — the 18-case adversarial supplement
   - `phase4_latency.py` — admission latency under load, default (fail-open) webhook config
   - To reproduce the fail-closed comparison (Phase 4b / Task A of the
     later addendum): apply `../policies/gatekeeper/webhook_failclosed_scoped.json`
     with `kubectl apply -f`, **back up your current webhook config first**
     (`kubectl get validatingwebhookconfiguration gatekeeper-validating-webhook-configuration -o yaml`),
     then run `phase4b_latency_failclosed.py`, `phase4b_admission_subset.py`,
     `phase4b_failure_injection.py` in turn.
   - `phase5_drift.py` — audit-controller drift-detection latency
   - `phase6_ci_overhead.py` — Conftest absolute execution-time overhead
   - `phase6b_over_metric.py` — Conftest overhead relative to a measured
     no-policy baseline (works without a cluster — see the script's own
     docstring for why `kubectl create --dry-run=client`, not `apply`,
     is used as the baseline)
   - `phase7_export_summary.py` — consolidates every phase's raw results
     into `results/summary_all_phases.json` (also cluster-free)
6. **Destroy the cluster.** `cd terraform && terraform apply -destroy` (or
   `terraform destroy`). Confirm nothing is left with the AWS Resource
   Groups Tagging API (`aws resourcegroupstaggingapi get-resources
   --tag-filters Key=Project,Values=c3-experiment`).

## Mapping paper results to this repository

The exact table/section numbers below reflect the manuscript structure as
described when this artifact was assembled — **verify these against your
current manuscript draft before submission**, since section numbering can
drift between revisions and this mapping was written from the experiment
side, not by re-reading the final manuscript text.

| Paper result | Produced by | Raw data |
|---|---|---|
| Detection rate / FPR, aggregate + per-category (Table 3, §5.C) | `scripts/phase3_admission_eval.py` | `results/phase3_admission_summary.json`, `results/phase3_admission_raw.csv` |
| Policy completeness gaps — 13/14 confirmed bypasses (§5.D) | `scripts/evaluate_adversarial.py` | `results/adversarial_results.csv` |
| Admission latency p50/p95/p99, fail-open, 3 concurrency tiers (Table 4, §6.G) | `scripts/phase4_latency.py` | `results/phase4_latency.json` |
| Admission latency, fail-closed comparison (§6.G addendum) | `scripts/phase4b_latency_failclosed.py` | `results/phase4b_latency_failclosed.json`, `results/phase4b_vs_phase4_comparison.csv` |
| Fail-closed detection parity + failure-injection test | `scripts/phase4b_admission_subset.py`, `scripts/phase4b_failure_injection.py` | `results/phase4b_admission_subset.json`, `results/phase4b_failure_injection.json` |
| Drift-detection latency (§6.G) | `scripts/phase5_drift.py` | `results/phase5_drift.json` |
| Conftest CI overhead, absolute (§6.H) | `scripts/phase6_ci_overhead.py` | `results/phase6_ci_overhead.json` |
| OVER metric, relative CI overhead (§6.H) | `scripts/phase6b_over_metric.py` | `results/phase6b_over_metric.json` |
| Consolidated cross-phase summary | `scripts/phase7_export_summary.py` | `results/summary_all_phases.json` |

## Safety & scope note

The adversarial supplement (§5.D, `results/adversarial_results.csv`)
documents 13 confirmed ways the *current* policy library's literal Rego
predicates can be bypassed by a semantically-equivalent but syntactically
different manifest (e.g. `hostPID`/`hostIPC` instead of `hostNetwork`,
capability grants instead of `privileged: true`, a `startswith()`-based
registry prefix match, binding to the built-in `cluster-admin` role instead
of creating a new over-permissive one). **These are documented as classes
of policy-completeness limitation, intended to guide defensive hardening of
the ControlSpec library** — they are not exploit code, do not target any
system beyond this artifact's own synthetic test namespace, and this
repository contains no attack tooling. Treat them the way you would a
static-analysis coverage report: a list of what the current ruleset does
*not* yet check, not an attack toolkit.

## License & citation

Licensed under Apache-2.0 (see `LICENSE`) — chosen over MIT for its
explicit patent grant, which is appropriate for a security-tooling
artifact; swap to MIT is a one-line change in `LICENSE`/`CITATION.cff` if
you'd prefer a more permissive license.

See `CITATION.cff` for citation metadata (software + the accompanying
Computers & Security article). Please fill in the `TODO:` placeholders
(DOI, release date, repository URL) once those exist — see
`RELEASE_CHECKLIST.md`.
