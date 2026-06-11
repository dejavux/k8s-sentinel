# Private / production cluster overlays

**Do not commit cluster-specific values to the public k8s-sentinel repo.**

Production overlays (internal registry, inventory, 1Password vault paths, GitOps target repo)
live in the **consumer** infrastructure repository.

## Example: 3q.fi (infra-bootstrap)

| File | Purpose |
|------|---------|
| `infra-bootstrap/deploy/k8s-sentinel/values-3q-prod.yaml` | Helm overlay (v0.2.7+) |
| `infra-bootstrap/deploy/k8s-sentinel/deploy.sh` | Inventory ConfigMap + SSH sync + Helm |
| `infra-bootstrap/40_k8s/inventory/hosts.yml` | Ansible inventory SSOT |
| `manifests/` (this folder) | Legacy smoke jobs + deprecated flat YAML (not for public apply) |

Install:

```bash
cd infra-bootstrap
make deploy APP=sentinel TAG=v0.2.7
```

## Generic public install

See [examples/helm/values-check-only.yaml](../helm/values-check-only.yaml) and [docs/INSTALL_HELM.md](../../docs/INSTALL_HELM.md).
