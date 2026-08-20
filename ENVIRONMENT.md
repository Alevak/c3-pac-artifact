# Environment — tool versions used

Versions actually used to produce the results in `results/`, as referenced
in the paper's Section 5.A. Two categories below: **directly confirmed**
(captured via `--version` calls during the actual experiment run) and
**best-effort reconstructed** (not captured live, recovered afterward from
local tooling state — flagged explicitly rather than presented as
certain).

## Directly confirmed

| Tool | Version | How confirmed |
|---|---|---|
| Terraform | v1.15.8 | `terraform version` |
| kubectl (client) | v1.33.0 | `kubectl version --client` |
| Kubernetes (EKS server) | v1.33.13-eks-254016e | `kubectl get nodes` output during Phase 1 |
| Conftest | 0.59.0 (embedded OPA 1.3.0) | `conftest --version` |
| Python | 3.14.5 | `python3 --version` |
| gitleaks (artifact sanitization only, not part of the experiment itself) | 8.30.1 | `brew install gitleaks` |

## Terraform provider / module versions (pinned in source, not just "used")

These are hard constraints in `terraform/versions.tf` and `terraform/main.tf`
— any `terraform init` will resolve to a version matching these constraints,
which is what actually governs reproducibility here (stronger than a
point-in-time version note):

- `hashicorp/aws` provider: `~> 5.70`
- `terraform-aws-modules/vpc/aws`: `~> 5.13`
- `terraform-aws-modules/eks/aws`: `~> 20.24`
- Kubernetes version requested from EKS: `1.33` (see `terraform/variables.tf`)

Note: `.terraform.lock.hcl` (which would pin exact resolved versions/hashes)
is intentionally **not** included in this artifact — regenerate it locally
with `terraform init` on first use, which will resolve to current versions
satisfying the constraints above. Provider patch releases within the `~>`
range should not materially affect reproduction; if you need the *exact*
resolved versions from the original run, they are not separately recorded
beyond what's stated here.

## Best-effort reconstructed (not directly captured at install time)

| Tool | Version | Caveat |
|---|---|---|
| Gatekeeper (Helm chart) | 3.23.0 (app version v3.23.0) | Installed via `helm install gatekeeper gatekeeper/gatekeeper` with **no explicit `--version` pin**, immediately after a `helm repo update`. This value is what the local Helm repo cache reports as current for that chart, checked shortly after the experiment concluded — not captured via `helm list -o json` at install time itself. For closest reproduction, install `gatekeeper/gatekeeper` at version `3.23.0` explicitly (`helm install gatekeeper gatekeeper/gatekeeper --version 3.23.0 ...`); a later 3.23.x patch is very unlikely to change enforcement behavior but hasn't been verified against this artifact's results. |

## Not applicable / not used

- No Python third-party packages (see `requirements.txt`) — no `pip`
  version dependency to record.
- No Docker/container runtime was used directly; all workloads in the
  synthetic corpus reference either real (`registry.k8s.io/pause:3.9`) or
  intentionally-nonexistent image references, evaluated purely at the
  Kubernetes admission-control layer (objects were never actually
  scheduled for most of the corpus — see the paper's Section 4/Phase 3
  methodology note on `--dry-run=server`).
