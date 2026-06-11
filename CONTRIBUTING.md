# Contributing

Thank you for improving k8s-sentinel.

## Development Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
npm ci
pytest
ruff check scripts/
```

## Pull Requests

1. Fork and branch from `main`.
2. Add or update tests for behavior changes.
3. Run `pytest` and `ruff check` locally.
4. Keep commits focused; use [Conventional Commits](https://www.conventionalcommits.org/) style.

## Check Modules

New modules: implement `BaseCheck` under `scripts/checks/`, register in the check registry, document in `docs/MODULES.md` (when present).

## Helm / Release

Chart changes require `helm lint charts/k8s-sentinel`. Releases are tagged `v*` and published to ghcr.io via GitHub Actions.
