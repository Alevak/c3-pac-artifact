package pci.k8s.tls

import rego.v1

violation contains v if {
  input.kind == "Ingress"
  ns := input.metadata.namespace
  startswith(ns, "cde-")
  not ingress_has_tls(input.spec)
  v := {
    "control_id": "PCI-Req4.2.1",
    "regulatory": ["PCI-DSS:Req4.2.1", "NIS2:Art21e"],
    "msg": sprintf("Ingress in CDE namespace %v must enforce TLS", [ns])
  }
}

ingress_has_tls(spec) if {
  count(spec.tls) > 0
}
