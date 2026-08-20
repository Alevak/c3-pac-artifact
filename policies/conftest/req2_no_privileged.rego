package pci.k8s.privileged

import rego.v1

violation contains v if {
  input.kind == "Pod"
  ns := input.metadata.namespace
  startswith(ns, "cde-")
  c := input.spec.containers[_]
  c.securityContext.privileged == true
  v := {
    "control_id": "PCI-Req2.2.1",
    "regulatory": ["PCI-DSS:Req2.2.1", "NIS2:Art21a"],
    "msg": sprintf("Privileged container not allowed in CDE: %v", [c.name])
  }
}
