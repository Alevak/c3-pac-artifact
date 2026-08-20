package pci.k8s.audit

import rego.v1

violation contains v if {
  input.kind == "Pod"
  ns := input.metadata.namespace
  startswith(ns, "cde-")
  not input.metadata.labels["audit-logging"] == "enabled"
  v := {
    "control_id": "PCI-Req10.2.1",
    "regulatory": ["PCI-DSS:Req10.2.1", "NIS2:Art21b"],
    "msg": sprintf("Pod in %v missing audit-logging=enabled label", [ns])
  }
}
