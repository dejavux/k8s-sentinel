# Changelog

All notable changes to this project are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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

[0.2.7]: https://github.com/dejavux/k8s-sentinel/compare/v0.2.4...v0.2.7
[0.2.4]: https://github.com/dejavux/k8s-sentinel/compare/v0.2.0...v0.2.4
[0.2.0]: https://github.com/dejavux/k8s-sentinel/releases/tag/v0.2.0
