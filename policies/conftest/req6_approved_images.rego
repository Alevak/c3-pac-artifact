package pci.k8s.images

import rego.v1

approved_registries := {
  "registry.k8s.io",
  "registry.corp.example",
  "gcr.io/trusted"
}

violation contains v if {
  input.kind == "Pod"
  ns := input.metadata.namespace
  startswith(ns, "cde-")
  c := input.spec.containers[_]
  not image_approved(c.image)
  v := {
    "control_id": "PCI-Req6.3.3",
    "regulatory": ["PCI-DSS:Req6.3.3", "NIS2:Art21e"],
    "msg": sprintf("Image registry not approved in CDE: %v", [c.image])
  }
}

image_approved(img) if {
  some reg in approved_registries
  startswith(img, reg)
}
