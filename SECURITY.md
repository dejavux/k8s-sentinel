# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| < 0.2   | No        |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security-sensitive reports.

1. Email the maintainer via GitHub profile contact, or open a **private** security advisory on
   [github.com/dejavux/k8s-sentinel/security/advisories](https://github.com/dejavux/k8s-sentinel/security/advisories).
2. Include: affected version, reproduction steps, impact, and suggested fix if any.
3. Expect an initial response within **7 days**.

## Scope

In scope:

- k8s-sentinel CronJob / Helm chart / bundled Ansible playbooks
- GitOps / Cursor integration when enabled by the operator
- Credential handling (Kubernetes Secrets, optional 1Password Operator)

Out of scope:

- Consumer cluster misconfiguration (e.g. `autoFix=true` on production without review)
- Compromise of SSH keys or GitHub tokens supplied by the cluster admin

## Safe Defaults

Public Helm values default to **check-only** (`autoFix=false`, `gitops.enabled=false`).
Enabling auto-remediation or GitOps PRs requires explicit operator opt-in.
