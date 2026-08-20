package pci.k8s.hostpath

import rego.v1

violation contains v if {
  input.kind == "Pod"
  ns := input.metadata.namespace
  startswith(ns, "cde-")
  vol := input.spec.volumes[_]
  vol.hostPath
  v := {
    "control_id": "PCI-Req2.2.1",
    "regulatory": ["PCI-DSS:Req2.2.1", "NIS2:Art21e"],
    "msg": sprintf("hostPath volume not allowed in CDE: %v", [vol.name])
  }
}
