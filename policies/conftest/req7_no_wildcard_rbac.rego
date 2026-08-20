package pci.k8s.rbac

import rego.v1

violation contains v if {
  input.kind == "ClusterRole"
  rule := input.rules[_]
  rule.resources[_] == "*"
  v := {
    "control_id": "PCI-Req7.2.1",
    "regulatory": ["PCI-DSS:Req7.2.1", "NIS2:Art21i"],
    "msg": sprintf("ClusterRole %v uses wildcard resources", [input.metadata.name])
  }
}

violation contains v if {
  input.kind == "ClusterRole"
  rule := input.rules[_]
  rule.verbs[_] == "*"
  v := {
    "control_id": "PCI-Req7.2.1",
    "regulatory": ["PCI-DSS:Req7.2.1", "NIS2:Art21i"],
    "msg": sprintf("ClusterRole %v uses wildcard verbs", [input.metadata.name])
  }
}
