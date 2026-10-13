# Security policy

The most valuable report this project can receive is a way for a candidate build to influence the evidence the
judge produces: a passing result for an application that does not satisfy the obligations, a frozen check that
can be made to report success without executing, an attestation accepted without an operator's key, or an
artifact digest that fails to cover a file the application loads.

Please report such findings privately by opening a GitHub Security Advisory on this repository (Security →
Advisories → Report a vulnerability). Include a minimal candidate that demonstrates the bypass; the validation
matrix in `validation/matrix.py` shows the expected shape. Reports are acknowledged within a week; fixes ship as
a new sealed release with the reproducing candidate added to `docs/VALIDATION.md`.

Scope notes: from v0.6.0 the supported isolation profile (`gate/isolation/` since v0.7.0) runs the candidate's service
and the browser as separate unprivileged users in a network-less container, and the gate observes those
restrictions with a probe before any candidate code runs. A candidate that can read the evidence directory, write
the judged policy, reach the network, or cause the probe to report "denied" for something it can in fact reach,
*inside that profile*, is in scope and is the most valuable report. Outside the profile (local advisory runs)
the candidate runs as the judge's user and these are known, reported limitations. Kernel and container-runtime
escapes are out of scope.
