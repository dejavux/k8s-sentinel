# Changelog

All notable changes to this project are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.9] - 2026-06-15

### Added

- GitOps eligibility gate (`SENTINEL_GITOPS_MODULES`); default `pods` only
- Post-GitOps Cursor cloud agent archive (`SENTINEL_CURSOR_ARCHIVE`)
- Optional CronJob Telegram summary (`SENTINEL_TELEGRAM_NOTIFY`)
- Bulk archive helper: `scripts/gitops/archive_sentinel_agents.ts`

### Changed

- autoPR no longer opens on generic fix failures (e.g. kube-proxy restart)
- `cursor_fix_pr.ts` uses `Agent.create` + `Agent.archive` instead of one-shot `Agent.prompt`

## [0.2.7] - 2026-06-10

### Added

- `resources` check module; Prometheus Pushgateway metrics export
- Cursor Agent **cloud** runtime for in-cluster GitOps E2E
- kubectl plugin (`bin/kubectl-sentinel`)

### Changed

- 3q production validated on v0.2.7 (7 modules, Telegram alerts)

## [0.2.4] - 2026-06-08

### Added

- Helm chart with check-only safe defaults
- Bundled `ansible/playbooks/fix-containerd-cri.yml`
- CI: pytest + ruff

## [0.2.0] - 2026-06-01

### Added

- Initial modular checks: runc, disk, pods, components, containerd, kubelet
- Optional Ansible remediation and GitOps PR flow

[0.2.9]: https://github.com/dejavux/k8s-sentinel/compare/v0.2.8...v0.2.9
[0.2.7]: https://github.com/dejavux/k8s-sentinel/compare/v0.2.4...v0.2.7
[0.2.4]: https://github.com/dejavux/k8s-sentinel/compare/v0.2.0...v0.2.4
[0.2.0]: https://github.com/dejavux/k8s-sentinel/releases/tag/v0.2.0
