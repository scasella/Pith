---- MODULE Integration ----
\* DEFECT (known-wrong integration): the coordinator records ACCEPTED as soon as the booking succeeds (RecordEarly) and
\* closes the saga over that receipt whatever quota says, so when quota refuses and the booking is cancelled the receipt
\* still says ACCEPTED. Every component keeps its own rules (a receipt is written once, the log moves forward, the
\* booking is cancelled once, quota never exceeds its limit), and the booking and the unit still agree: only the
\* receipt and the components do not.
EXTENDS Booking, Quota, Coordinator
VARIABLES up, ans
vars == <<bk, grants, saga, receipt, up, ans>>

Init == BookingInit /\ QuotaInit /\ CoordinatorInit /\ up = TRUE /\ ans = [r \in Reqs |-> "none"]

InFlight(r) == saga[r] \notin {"idle", "done"}
SetAns(r, v) == ans' = [ans EXCEPT ![r] = v]

Begin(r) == up /\ CoordLog(r, "begun") /\ UNCHANGED <<bk, grants, up, ans>>
CallBook(r) ==
    /\ up /\ saga[r] = "begun" /\ ans[r] = "none"
    /\ \/ bk[r] # "none" /\ SetAns(r, "booked") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
       \/ BookAccept(r) /\ SetAns(r, "booked") /\ UNCHANGED <<grants, saga, receipt, up>>
       \/ bk[r] = "none" /\ SetAns(r, "refused") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
LogBooked(r) == up /\ ans[r] = "booked" /\ CoordLog(r, "booked") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
RecordEarly(r) == up /\ saga[r] = "booked" /\ CoordRecord(r, "ACCEPTED") /\ UNCHANGED <<bk, grants, up, ans>>
LogRefused(r) == up /\ saga[r] = "begun" /\ ans[r] = "refused" /\ CoordFinish(r, "CONFLICT") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
CallQuota(r) ==
    /\ up /\ saga[r] = "booked" /\ receipt[r] # "none" /\ ans[r] = "none"
    /\ \/ r \in grants /\ SetAns(r, "granted") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
       \/ QuotaGrant(r) /\ SetAns(r, "granted") /\ UNCHANGED <<bk, saga, receipt, up>>
       \/ r \notin grants /\ ~QuotaCanGrant(r) /\ SetAns(r, "denied") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
LogGranted(r) == up /\ saga[r] = "booked" /\ ans[r] = "granted" /\ CoordClose(r) /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
LogDenied(r) == up /\ ans[r] = "denied" /\ CoordLog(r, "denied") /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>
CallCancel(r) ==
    /\ up /\ saga[r] = "denied" /\ ans[r] = "none"
    /\ \/ bk[r] = "cancelled" /\ SetAns(r, "cancelled") /\ UNCHANGED <<bk, grants, saga, receipt, up>>
       \/ BookCancel(r) /\ SetAns(r, "cancelled") /\ UNCHANGED <<grants, saga, receipt, up>>
LogCancelled(r) == up /\ saga[r] = "denied" /\ ans[r] = "cancelled" /\ CoordClose(r) /\ SetAns(r, "none") /\ UNCHANGED <<bk, grants, up>>

Crash == up /\ up' = FALSE /\ ans' = [r \in Reqs |-> "none"] /\ UNCHANGED <<bk, grants, saga, receipt>>
Restart == ~up /\ up' = TRUE /\ UNCHANGED <<bk, grants, saga, receipt, ans>>

Next == \/ Crash \/ Restart
        \/ \E r \in Reqs : Begin(r) \/ CallBook(r) \/ LogBooked(r) \/ RecordEarly(r) \/ LogRefused(r) \/ CallQuota(r)
                           \/ LogGranted(r) \/ LogDenied(r) \/ CallCancel(r) \/ LogCancelled(r)
Spec == Init /\ [][Next]_vars
====
