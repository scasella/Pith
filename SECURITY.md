# Security policy

The most valuable report this project can receive is a way for a candidate build to influence the evidence the
judge produces: a passing result for an application that does not satisfy the obligations, a frozen check that
can be made to report success without executing, an attestation accepted without an operator's key, or an
artifact digest that fails to cover a file the application loads.

Please report such findings privately by opening a GitHub Security Advisory on this repository (Security →
Advisories → Report a vulnerability). Include a minimal candidate that demonstrates the bypass; the validation
matrix in `validation/matrix.py` shows the expected shape. Reports are acknowledged within a week; fixes ship as
a new sealed release with the reproducing candidate added to `docs/VALIDATION.md`.

Scope notes: the judge isolates candidate code by process, not by sandbox. Attacks that require the candidate
to already have write access to the evaluator, the operator's keys, or the evidence directory are out of scope
and documented as operational requirements in `README.md`.
