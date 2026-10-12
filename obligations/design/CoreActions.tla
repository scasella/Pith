---------------------------- MODULE CoreActions ----------------------------
(* Ring-1 obligations. BOTH proven kernels (authorization: Decide/Release; posting: Capture) as
   atomic TLA+ actions over the shared state, plus the invariants any design around them must keep.
   INV1 is the composition invariant: no single kernel owns it, every kernel can break it, and only
   this model checks it under interleaving. The agent writes design/Design.tla, which EXTENDS this module,
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
VARIABLES status,  \* Reqs -> {"None","Auth","Decl","Rel","Post"}
          held,    \* subset of Reqs with a live hold
          posted   \* Nat: amount captured so far (the posting kernel's state)
coreVars == <<status, held, posted>>

RECURSIVE SumSet(_)
SumSet(S) == IF S = {} THEN 0 ELSE LET r == CHOOSE x \in S : TRUE IN Amount[r] + SumSet(S \ {r})
Reserved  == SumSet(held)
Available == Limit - posted - Reserved          \* the figure the core must be given at the decision step

CoreInit == status = [r \in Reqs |-> "None"] /\ held = {} /\ posted = 0

\* Decide(a, r) with the availability the design hands it. A correct design hands it Available
\* in the same step; a design that hands it an earlier reading will fail INV1.
CoreDecide(r, avail) ==
  /\ status[r] = "None"
  /\ IF Amount[r] <= avail
       THEN status' = [status EXCEPT ![r] = "Auth"] /\ held' = held \cup {r}        \* [P0]
       ELSE status' = [status EXCEPT ![r] = "Decl"] /\ held' = held                 \* [P1]
  /\ UNCHANGED posted
CoreDecision(r) == IF status[r] = "Decl" THEN "Decl" ELSE "Auth"   \* recorded decision (Rel/Post count as Auth)
CoreReplay(r)  == status[r] # "None" /\ UNCHANGED coreVars           \* idempotent replay: core not called
CoreRelease(r) == status[r] = "Auth" /\ status' = [status EXCEPT ![r] = "Rel"] /\ held' = held \ {r} /\ UNCHANGED posted   \* [R1][R2]
\* The posting kernel's Capture: hold removed, exact amount posted, request terminal.
CoreCapture(r) == status[r] = "Auth" /\ status' = [status EXCEPT ![r] = "Post"] /\ held' = held \ {r} /\ posted' = posted + Amount[r]   \* [C1][C2][C3]

\* Obligations ------------------------------------------------------------------
\* DecideCorrect binds every decision to the availability of the SAME step (pre-state). A design
\* that hands CoreDecide a stale, constant or invented figure fails here even if INV1 happens to hold.
DecideCorrect == [][\A r \in Reqs :
                    (status[r] = "None" /\ status'[r] # "None")
                      => (status'[r] = "Auth" <=> Amount[r] <= Available)]_coreVars
INV1 == posted + Reserved <= Limit                      \* the COMPOSITION invariant
P2   == held = {r \in Reqs : status[r] = "Auth"}
P3   == [][\A r \in Reqs : status[r] = "Decl" => status'[r] = "Decl"]_coreVars
P4   == [][\A r \in Reqs : status[r] = "Post" => status'[r] = "Post"]_coreVars      \* Post is terminal
PostedExact == [][posted' >= posted]_coreVars             \* posting never decreases (no un-capture)
IdempotentResp(responses) == \A r \in Reqs : \A i, j \in 1..Len(responses[r]) : responses[r][i] = responses[r][j]
ConsistentResp(responses) == \A r \in Reqs : Len(responses[r]) > 0 => responses[r][1] = CoreDecision(r)

\* Coverage obligations: each must be VIOLATED by the design (TLC finds a behaviour reaching it).
CovDecided    == \A r \in Reqs : status[r] = "None"                         \* something is ever decided
CovContention == \A r \in Reqs : status[r] = "None" \/ held \ {r} = {}         \* a decision is made while another hold is live
CovDecline    == \A r \in Reqs : status[r] # "Decl" \/ held = {}              \* a decline happens with funds reserved
CovRelease    == \A r \in Reqs : status[r] # "Rel"                           \* a release happens
CovCapture    == \A r \in Reqs : status[r] # "Post"                          \* a capture happens
CovCaptureContention == \A r \in Reqs : status[r] # "Post" \/ \A q \in Reqs : status[q] # "None"   \* a capture lands while another request is still undecided
RetryCov(responses) == \A r \in Reqs : Len(responses[r]) <= 1                \* a client sees a second response (retry)
=============================================================================
