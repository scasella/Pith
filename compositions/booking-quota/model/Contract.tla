---- MODULE Contract ----
\* The joint obligations no component can state alone. Both are required at rest: for a request that is not in flight, as
\* the integration defines InFlight (the coordinator is mid-saga on it). While a saga runs, the booking and the quota unit are
\* legitimately apart (a booking whose unit is not yet taken); the obligation is that nothing leaves them apart once the
\* request is no longer in flight, whatever crashed on the way. That a logged saga is resumed after a restart, so that it
\* does leave flight, is not a safety property: the runtime tests check it.
EXTENDS Integration
AtRest(r) == ~InFlight(r)
Active(r) == bk[r] = "active"
Granted(r) == r \in grants

\* A request's booking is active exactly when its quota unit is granted: no booking without its unit, no unit without its booking.
QuotaMatchesBookings == \A r \in Reqs : AtRest(r) => (Active(r) <=> Granted(r))

\* A receipt that has been written agrees with the components: ACCEPTED exactly when the booking is active and its unit
\* granted; QUOTA_EXCEEDED only for a booking that was cancelled with no unit; CONFLICT only when there is no booking.
ReceiptAgrees == \A r \in Reqs : (AtRest(r) /\ receipt[r] # "none") =>
    /\ (receipt[r] = "ACCEPTED") <=> (Active(r) /\ Granted(r))
    /\ (receipt[r] = "QUOTA_EXCEEDED" => bk[r] = "cancelled" /\ ~Granted(r))
    /\ (receipt[r] = "CONFLICT" => bk[r] = "none" /\ ~Granted(r))
====
