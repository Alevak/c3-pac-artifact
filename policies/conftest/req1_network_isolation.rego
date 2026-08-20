package pci.k8s.network

import rego.v1

violation contains v if {
  input.kind == "Pod"
  ns := input.metadata.namespace
  input.metadata.labels["pci-cde"] == "true"
  not namespace_has_default_deny(ns)
  v := {
    "control_id": "PCI-Req1.3.1",
    "regulatory": ["PCI-DSS:Req1.3.1", "NIS2:Art21a"],
    "msg": sprintf("CDE namespace %v lacks default-deny NetworkPolicy", [ns])
  }
}

namespace_has_default_deny(ns) if {
  some np in data.networkpolicies[ns]
  count(np.spec.podSelector) == 0
  count(np.spec.ingress) == 0
}
