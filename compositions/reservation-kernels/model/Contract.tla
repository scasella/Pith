---- MODULE Contract ----
\* The joint obligations neither kernel can state alone.
EXTENDS Integration
\* [INV1] posted plus reserved never exceeds the limit: the posting kernel owns one term, the authorization kernel the other.
INV1 == posted + Reserved <= Limit
\* A request is Post in the authorization kernel exactly when the posting kernel has posted it.
CaptureAgrees == captured = {r \in Reqs : status[r] = "Post"}
====
