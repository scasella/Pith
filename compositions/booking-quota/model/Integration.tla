---- MODULE Integration ----
\* The integration: a reservation is a saga the coordinator drives across the components. Every call to a component is one
\* atomic step at that component; its answer is held in the coordinator's memory (ans) until the coordinator logs what it
\* means, in a second step. A crash loses ans, the process and nothing else: the coordinator's log and receipts are
\* durable, so after a restart the coordinator resumes every logged saga from its last logged step (the calls are
\* idempotent, so a repeated call returns what the component recorded). A client's retry of a request whose saga is
\* in flight drives the same saga and is not modelled separately.
\*
\* Ordering: log "begun" before the booking is called; call booking; log "booked" (or finish with CONFLICT when the booking
\* refused); call quota; finish with ACCEPTED when granted, otherwise log "denied" BEFORE the cancel is issued; call
\* the cancel; finish with QUOTA_EXCEEDED once the booking is cancelled.
EXTENDS Booking, Quota, Coordinator
VARIABLES up, ans
vars == <<bk, grants, saga, receipt, up, ans>>

Init == BookingInit /\ QuotaInit /\ CoordinatorInit /\ up = TRUE /\ ans = [r \in Reqs |-> "none"]

\* A request is in flight from the moment its saga is logged until it is done.
InFlight(r) == saga[r] \notin {"idle", "done"}
SetAns(r, v) == ans' = [ans EXCEPT ![r] = v]

Begin(r) == up /\ CoordLog(r, "begun") /\ UNCHANGED <<bk, grants, up, ans>>
CallBook(r) ==
    /\ up /\ saga[r] = "begun" /\ ans[r] = "none"
    /\ \/ bk[r] # "none" /\ SetAns(r, "booked") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
       \/ BookAccept(r) /\ SetAns(r, "booked") /\ UNCHANGED <<grants, saga, receipt, up>>
       \/ bk[r] = "none" /\ SetAns(r, "refused") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
LogBooked(r) == up /\ ans[r] = "booked" /\ CoordLog(r, "booked") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
LogRefused(r) == up /\ saga[r] = "begun" /\ ans[r] = "refused" /\ CoordFinish(r, "CONFLICT") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
CallQuota(r) ==
    /\ up /\ saga[r] = "booked" /\ ans[r] = "none"
    /\ \/ r \in grants /\ SetAns(r, "granted") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
       \/ QuotaGrant(r) /\ SetAns(r, "granted") /\ UNCHANGED <<bk, saga, receipt, up>>
       \/ r \notin grants /\ ~QuotaCanGrant(r) /\ SetAns(r, "denied") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
LogGranted(r) == up /\ saga[r] = "booked" /\ ans[r] = "granted" /\ CoordFinish(r, "ACCEPTED") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
LogDenied(r) == up /\ ans[r] = "denied" /\ CoordLog(r, "denied") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
CallCancel(r) ==
    /\ up /\ saga[r] = "denied" /\ ans[r] = "none"
    /\ \/ bk[r] = "cancelled" /\ SetAns(r, "cancelled") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
       \/ BookCancel(r) /\ SetAns(r, "cancelled") /\ UNCHANGED <<grants, saga, receipt, up>>
LogCancelled(r) == up /\ saga[r] = "denied" /\ ans[r] = "cancelled" /\ CoordFinish(r, "QUOTA_EXCEEDED") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>

Crash == up /\ up' = FALSE /\ ans' = [r \in Reqs |-> "none"] /\ UNCHANGED <<bk, grants, saga, receipt>>
Restart == ~up /\ up' = TRUE /\ UNCHANGED <<bk, grants, saga, receipt, ans>>

Next == \/ Crash \/ Restart
        \/ \E r \in Reqs : Begin(r) \/ CallBook(r) \/ LogBooked(r) \/ LogRefused(r) \/ CallQuota(r) \/ LogGranted(r)
                           \/ LogDenied(r) \/ CallCancel(r) \/ LogCancelled(r)
Spec == Init /\ [][Next]_vars
====
