---- MODULE Common ----
\* What every component reads and none owns: the reservation requests and the quota's limit for a resource. The model has
\* one resource and two requests; the runtime check (runtime/harness.py) is per resource.
EXTENDS Naturals, FiniteSets
CONSTANTS Reqs, Limit
====
