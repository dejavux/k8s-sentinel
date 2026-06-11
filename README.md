# k8s-sentinel

**Self-hosted Kubernetes health checks and optional auto-healing for bare-metal and homelab clusters.**

[![CI](https://github.com/dejavux/k8s-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/dejavux/k8s-sentinel/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

k8s-sentinel runs as a **CronJob** every 30 minutes (configurable). It scans your cluster for common failure modes — disk pressure, containerd CRI issues, kube-proxy, abnormal pods — and can optionally repair them via **kubectl** or **Ansible over SSH**.

**Safe defaults**: `autoFix=false`, `autoPR=false`. Start with check-only, then enable fixes after review.

---

## Quick start (check-only)

```bash
helm upgrade --install k8s-sentinel oci://ghcr.io/dejavux/charts/k8s-sentinel \
  --version 0.2.7 \
  -n kube-system
```

Or from this repo:

```bash
helm upgrade --install k8s-sentinel ./charts/k8s-sentinel \
  -n kube-system \
  -f examples/helm/values-check-only.yaml
```

Trigger a manual run:

```bash
kubectl create job --from=cronjob/k8s-sentinel sentinel-check-$(date +%s) -n kube-system
kubectl logs -n kube-system job/sentinel-check-... -f
```

See [docs/INSTALL_HELM.md](docs/INSTALL_HELM.md) for Ansible SSH, 1Password Operator, and GitOps overlays.

---

## Modules

| Module | Checks | Auto-fix (when enabled) |
|--------|--------|-------------------------|
| `runc` | runc availability | Ansible |
| `disk` | DiskPressure, rootfs usage | Ansible + optional CI prune |
| `containerd` | CRI Unknown, NodeStatusUnknown | fix-containerd-cri playbook |
| `kubelet` | NotReady nodes | uncordon / systemctl |
| `pods` | CrashLoop, Pending, etc. | Pod restart + optional GitOps PR |
| `components` | kube-proxy, CoreDNS | Pod restart |
| `resources` | Memory/PID pressure, `kubectl top` | Alert only |

---

## Architecture

```text
CronJob (every 30m)
  └─ k8s-sentinel check
       ├─ checks/     → module registry (Python)
       ├─ fixers/     → Ansible runner (optional SSH)
       ├─ gitops/     → PR creator (experimental)
       └─ metrics/    → Prometheus text exposition (optional)
```

**Bare-metal SSH**: enable `ansible.enabled=true`, mount inventory ConfigMap + SSH secret. See `examples/helm/values-ansible.yaml`.

**Secrets**: use Kubernetes Secret (`manifests/overlays/generic/`) or 1Password Operator (`manifests/overlays/onepassword/`).

---

## Configuration

| Env / values | Description | Default |
|--------------|-------------|---------|
| `config.modules` | Comma-separated modules | all 7 |
| `config.autoFix` | Apply repairs | `false` |
| `config.autoPR` | Open GitOps PR on failure | `false` |
| `ansible.enabled` | Mount inventory + SSH | `false` |
| `gitops.githubRepo` | Target repo for PRs | `""` (required if GitOps on) |
| `SENTINEL_INFRA_ROOT` | External monorepo for optional playbooks | optional |
| `SENTINEL_GITHUB_REPO` | GitOps clone target | required when GitOps enabled |

Full reference: [docs/INSTALL_HELM.md](docs/INSTALL_HELM.md).

---

## Development

```bash
make test          # pytest
make lint-ci       # ruff
npm ci             # GitOps TypeScript deps
```

CI runs on every push/PR to `main`.

---

## Releases

Tag `v*` triggers [`.github/workflows/release.yml`](.github/workflows/release.yml):

- Container: `ghcr.io/dejavux/k8s-sentinel:<tag>`
- Helm chart: attached to GitHub Release

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [INSTALL_HELM.md](docs/INSTALL_HELM.md) | Install guide |
| [PUBLIC_REPO_PLAN.md](docs/PUBLIC_REPO_PLAN.md) | Open-source roadmap |
| [GO_TO_MARKET.md](docs/GO_TO_MARKET.md) | Promotion, grants, TA (maintainers) |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |

Production overlays for private clusters: [examples/private-cluster/](examples/private-cluster/README.md).

---

## License

Apache-2.0 — see [LICENSE](LICENSE).
