# Pith as a verification step in a Spec Kit workflow

[GitHub Spec Kit](https://github.com/github/spec-kit) structures work as specify, plan, tasks and implement, with the
agent's slash commands driving each step. Pith does not replace any of that. It adds one step after implementation:
judge the result against an independently maintained contract pack, and hand the agent a task packet when it fails.

`pith.verify.md` is that step as an agent command. Put it where your agent reads its Spec Kit commands (next to the
`speckit.*` command files your Spec Kit installation created for your agent), named so it sorts after them. It assumes:

- the project is a Pith seed checkout, or an existing project adopted per `docs/ADOPTING.md`;
- the operator's pinned release digest is in the environment as `PITH_RELEASE`, and, for an adopted project, the
  pristine release directory as `PITH_RELEASE_DIR` (both set by a person, outside the agent's reach).

What the command lets the agent do: run the judge, read the packet, fix its own files for `violation`,
`not_exercised` and `evidence_missing`, and stop and report for the other three categories. What it does not let the
agent do: edit anything frozen, change the pack, or call a blocked check passed. The authoritative verdict remains
the operator's pinned run.

Spec Kit's spec and plan stay the place for intent and design. When a Spec Kit spec asks for behaviour the pack's
contract does not allow, the packet reports `contract_change`: that is a change to the contract, made by its
maintainers through a new pack release, not something the agent implements around it.
