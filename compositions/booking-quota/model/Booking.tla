---- MODULE Booking ----
\* Component "booking" (a pith.booking service): owns bk, the state of each request's booking. A booking is accepted once
\* and may be cancelled once; a cancelled booking never becomes active again. Whether the booking REFUSES a request
\* (a conflicting interval) is the component's own decision and is not modelled here: the integration treats it as a
\* nondeterministic answer that changes nothing.
EXTENDS Common
VARIABLE bk

BookingInit == bk = [r \in Reqs |-> "none"]
BookAccept(r) == bk[r] = "none" /\ bk' = [bk EXCEPT ![r] = "active"]
BookCancel(r) == bk[r] = "active" /\ bk' = [bk EXCEPT ![r] = "cancelled"]

\* Local invariant, over this component's state only.
BookingInv == bk \in [Reqs -> {"none", "active", "cancelled"}]
====
