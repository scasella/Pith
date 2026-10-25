---- MODULE Integration ----
\* DEFECT (known-wrong integration): the coordinator keeps an in-flight saga only in memory (vsaga). Nothing is logged
\* before the booking is called, and the durable log (saga) is written only when a reservation is finished, so a crash
\* between the booking and the quota call forgets the saga: the booking stays active, no unit is ever granted, and nothing
\* resumes it. Every component keeps its own rules (the booking only accepts and cancels, quota never exceeds its limit,
\* the coordinator's log moves only through Finish, a receipt is written once), yet the booking and the unit disagree.
EXTENDS Booking, Quota, Coordinator
VARIABLES up, ans, vsaga
vars == <<bk, grants, saga, receipt, up, ans, vsaga>>

Init == BookingInit /\ QuotaInit /\ CoordinatorInit /\ up = TRUE /\ ans = [r \in Reqs |-> "none"] /\ vsaga = [r \in Reqs |-> "idle"]

InFlight(r) == vsaga[r] # "idle"
SetAns(r, v) == ans' = [ans EXCEPT ![r] = v]
SetV(r, v) == vsaga' = [vsaga EXCEPT ![r] = v]

Begin(r) == up /\ saga[r] = "idle" /\ vsaga[r] = "idle" /\ SetV(r, "begun") /\ UNCHANGED <<bk, grants, saga, receipt, up, ans>>
CallBook(r) ==
    /\ up /\ vsaga[r] = "begun" /\ ans[r] = "none"
    /\ \/ bk[r] # "none" /\ SetAns(r, "booked") /\ UNCHANGED <<bk, grants, saga, receipt, up, vsaga>>
       \/ BookAccept(r) /\ SetAns(r, "booked") /\ UNCHANGED <<grants, saga, receipt, up, vsaga>>
       \/ bk[r] = "none" /\ SetAns(r, "refused") /\ UNCHANGED <<bk, grants, saga, receipt, up, vsaga>>
LogBooked(r) == up /\ vsaga[r] = "begun" /\ ans[r] = "booked" /\ SetV(r, "booked") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
LogRefused(r) == up /\ vsaga[r] = "begun" /\ ans[r] = "refused" /\ CoordFinish(r, "CONFLICT") /\ SetV(r, "idle") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
CallQuota(r) ==
    /\ up /\ vsaga[r] = "booked" /\ ans[r] = "none"
    /\ \/ r \in grants /\ SetAns(r, "granted") /\ UNCHANGED <<bk, grants, saga, receipt, up, vsaga>>
       \/ QuotaGrant(r) /\ SetAns(r, "granted") /\ UNCHANGED <<bk, saga, receipt, up, vsaga>>
       \/ r \notin grants /\ ~QuotaCanGrant(r) /\ SetAns(r, "denied") /\ UNCHANGED <<bk, grants, saga, receipt, up, vsaga>>
LogGranted(r) == up /\ vsaga[r] = "booked" /\ ans[r] = "granted" /\ CoordFinish(r, "ACCEPTED") /\ SetV(r, "idle") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
LogDenied(r) == up /\ vsaga[r] = "booked" /\ ans[r] = "denied" /\ SetV(r, "denied") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
CallCancel(r) ==
    /\ up /\ vsaga[r] = "denied" /\ ans[r] = "none"
    /\ \/ bk[r] = "cancelled" /\ SetAns(r, "cancelled") /\ UNCHANGED <<bk, grants, saga, receipt, up, vsaga>>
       \/ BookCancel(r) /\ SetAns(r, "cancelled") /\ UNCHANGED <<grants, saga, receipt, up, vsaga>>
LogCancelled(r) == up /\ vsaga[r] = "denied" /\ ans[r] = "cancelled" /\ CoordFinish(r, "QUOTA_EXCEEDED") /\ SetV(r, "idle") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>

\* The crash forgets everything the process held, including the sagas in flight.
Crash == up /\ up' = FALSE /\ ans' = [r \in Reqs |-> "none"] /\ vsaga' = [r \in Reqs |-> "idle"] /\ UNCHANGED <<bk, grants, saga, receipt>>
Restart == ~up /\ up' = TRUE /\ UNCHANGED <<bk, grants, saga, receipt, ans, vsaga>>

Next == \/ Crash \/ Restart
        \/ \E r \in Reqs : Begin(r) \/ CallBook(r) \/ LogBooked(r) \/ LogRefused(r) \/ CallQuota(r) \/ LogGranted(r)
                           \/ LogDenied(r) \/ CallCancel(r) \/ LogCancelled(r)
Spec == Init /\ [][Next]_vars
====
