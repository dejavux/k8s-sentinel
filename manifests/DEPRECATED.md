# Deprecated — use Helm chart

Flat manifests in this directory are **no longer applied** by `deploy.sh` or `make deploy APP=sentinel`.

**Source of truth:** `charts/k8s-sentinel/` (`helm upgrade --install k8s-sentinel …`)

| Legacy file | Helm equivalent |
|-------------|-----------------|
| `rbac.yaml` | `templates/rbac.yaml` |
| `cronjob.yaml` | `templates/cronjob.yaml` |
| `1password-items.yaml` | `templates/onepassworditem.yaml` (when `onepassword.enabled`) |

Kept for reference and smoke jobs (`job-phase*.yaml`, preload helpers). Do not `kubectl apply` rbac/cronjob alongside the Helm release.
