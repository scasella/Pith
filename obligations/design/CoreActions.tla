---------------------------- MODULE CoreActions ----------------------------
(* Ring-1 obligations. The proven core as atomic TLA+ actions, plus the invariants any
   design around it must keep. The agent writes design/Design.tla, which EXTENDS this module,
   adds its own variables (clients, retries, queues, locks) and actions, and must:
     - change `status`/`held` ONLY through CoreDecide, CoreReplay, CoreRelease;
     - pass INV1, P2, P3 and the response obligations with TLC;
     - declare a VARIABLE `responses` : Reqs -> Seq({"Auth","Decl"}) (what each client has seen);
       the frozen MC.tla binds Idempotent, Consistent and CovRetry to it. The design must not define those names.
   The design must also EXHIBIT behaviour: the coverage obligations below are invariants the
   gate requires TLC to VIOLATE (retries happen, decisions happen under contention, declines
   happen while holds are live, releases happen). A design that models too little fails them.
   This file is frozen; gate/frozen.sha256 covers it.                                   *)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS Reqs, Amount, Limit
VARIABLES status,  \* Reqs -> {"None","Auth","Decl","Rel"}
          held     \* subset of Reqs with a live hold
coreVars == <<status, held>>

RECURSIVE SumSet(_)
SumSet(S) == IF S = {} THEN 0 ELSE LET r == CHOOSE x \in S : TRUE IN Amount[r] + SumSet(S \ {r})
Posted    == 0
Reserved  == SumSet(held)
Available == Limit - Posted - Reserved          \* the figure the core must be given at the decision step

CoreInit == status = [r \in Reqs |-> "None"] /\ held = {}

\* Decide(a, r) with the availability the design hands it. A correct design hands it Available
\* in the same step; a design that hands it an earlier reading will fail INV1.
CoreDecide(r, avail) ==
  /\ status[r] = "None"
  /\ IF Amount[r] <= avail
       THEN status' = [status EXCEPT ![r] = "Auth"] /\ held' = held \cup {r}        \* [P0]
       ELSE status' = [status EXCEPT ![r] = "Decl"] /\ held' = held                 \* [P1]
CoreDecision(r) == IF status[r] = "Decl" THEN "Decl" ELSE "Auth"   \* recorded decision (Rel counts as Auth)
CoreReplay(r)  == status[r] # "None" /\ UNCHANGED coreVars           \* idempotent replay: core not called
CoreRelease(r) == status[r] = "Auth" /\ status' = [status EXCEPT ![r] = "Rel"] /\ held' = held \ {r}   \* [R1][R2]

\* Obligations ------------------------------------------------------------------
\* DecideCorrect binds every decision to the availability of the SAME step (pre-state). A design
\* that hands CoreDecide a stale, constant or invented figure fails here even if INV1 happens to hold.
DecideCorrect == [][\A r \in Reqs :
                    (status[r] = "None" /\ status'[r] # "None")
                      => (status'[r] = "Auth" <=> Amount[r] <= Available)]_coreVars
INV1 == Posted + Reserved <= Limit
P2   == held = {r \in Reqs : status[r] = "Auth"}
P3   == [][\A r \in Reqs : status[r] = "Decl" => status'[r] = "Decl"]_coreVars
IdempotentResp(responses) == \A r \in Reqs : \A i, j \in 1..Len(responses[r]) : responses[r][i] = responses[r][j]
ConsistentResp(responses) == \A r \in Reqs : Len(responses[r]) > 0 => responses[r][1] = CoreDecision(r)

\* Coverage obligations: each must be VIOLATED by the design (TLC finds a behaviour reaching it).
CovDecided    == \A r \in Reqs : status[r] = "None"                         \* something is ever decided
CovContention == \A r \in Reqs : status[r] = "None" \/ held \ {r} = {}         \* a decision is made while another hold is live
CovDecline    == \A r \in Reqs : status[r] # "Decl" \/ held = {}              \* a decline happens with funds reserved
CovRelease    == \A r \in Reqs : status[r] # "Rel"                           \* a release happens
RetryCov(responses) == \A r \in Reqs : Len(responses[r]) <= 1                \* a client sees a second response (retry)
=============================================================================
