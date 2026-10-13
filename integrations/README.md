# Integrations

Thin wrappers over Pith's command-line interface (`gate/cli.py`, RFC 0003 § 4). Each one calls the CLI and reads the
task packet; none of them judges anything, holds policy, or can change what passes. If a wrapper and the CLI disagree,
the CLI is right.

| Directory | For |
|---|---|
| `spec-kit/` | an independent behavioural-verification step in a GitHub Spec Kit workflow |

The pattern for any other agent or tool: run `python3 gate/cli.py verify --json -- <app_gate.py arguments>`, read
`state` and `first_failure` from the JSON on stdout, act on `first_failure.category` (only `violation`,
`not_exercised` and `evidence_missing` are the agent's to fix), and rerun with `rerun.full`.
