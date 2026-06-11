# Deprecated — use Helm chart

Flat manifests in this directory are **no longer applied** by default installs.

**Source of truth:** `charts/k8s-sentinel/` (`helm upgrade --install k8s-sentinel …`)

| Legacy / reference | Location |
|--------------------|----------|
| `rbac.yaml` | Helm `templates/rbac.yaml` |
| Production CronJob + smoke jobs | `examples/private-cluster/manifests/` (cluster-specific) |
| Generic secrets | `overlays/generic/` |
| 1Password | `overlays/onepassword/` |

Do not `kubectl apply` legacy rbac/cronjob alongside the Helm release.
