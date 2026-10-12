#!/usr/bin/env python3
"""gate/review.py — signed human-review attestations (Ed25519). FROZEN.

    python3 gate/review.py keygen --out reviewer            -> reviewer.key (private, keep off the agent's machine), reviewer.pub
    python3 gate/review.py sign --key reviewer.key --artifact <digest> --release <digest> \\
        --decide E1=approved --decide E2=approved --decide E3=rejected --expires 2026-12-31 --reviewer "name/role" --out review.json
    (verification is done by gate/app_gate.py --review review.json --reviewer-key reviewer.pub)

An attestation binds decisions to one artifact digest and one release digest; it cannot be reused for another
build, cannot be produced by the candidate (no key), and expires. The gate reports approved only from a valid
attestation covering every required evaluation; the table in app/SPEC.md is informational."""
import argparse, base64, json, pathlib, sys, time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

def canonical(obj): return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

def keygen(out):
    k = Ed25519PrivateKey.generate()
    pathlib.Path(out + ".key").write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    pathlib.Path(out + ".pub").write_bytes(k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    pathlib.Path(out + ".key").chmod(0o600)

def sign(args):
    key = serialization.load_pem_private_key(pathlib.Path(args.key).read_bytes(), password=None)
    decisions = dict(d.split("=", 1) for d in args.decide)
    for v in decisions.values():
        if v not in ("approved", "rejected"): sys.exit("decisions must be approved|rejected")
    payload = {"format": 1, "artifact_digest": args.artifact, "release_digest": args.release, "decisions": decisions,
               "reviewer": args.reviewer, "signed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "expires": args.expires}
    att = {"payload": payload, "signature": base64.b64encode(key.sign(canonical(payload))).decode()}
    pathlib.Path(args.out).write_text(json.dumps(att, indent=2) + "\n"); print(f"signed {args.out}")

def verify(review_path, pub_path, *, artifact_digest, release_digest, required_ids, today=None):
    """Returns (status, detail). status: approved | rejected | pending."""
    if not review_path: return "pending", {"reason": "no attestation supplied"}
    if not pub_path: return "pending", {"reason": "no reviewer public key supplied; attestations are verified only against an operator-held key"}
    try:
        att = json.loads(pathlib.Path(review_path).read_text()); payload, sig = att["payload"], base64.b64decode(att["signature"])
        pub = serialization.load_pem_public_key(pathlib.Path(pub_path).read_bytes())
        pub.verify(sig, canonical(payload))
    except InvalidSignature:
        return "rejected", {"reason": "signature invalid"}
    except Exception as e:
        return "rejected", {"reason": f"attestation unreadable: {e}"}
    # payload schema, independent of the signer
    d = payload.get("decisions")
    if not (isinstance(d, dict) and d and all(isinstance(k, str) and v in ("approved", "rejected") for k, v in d.items())):
        return "rejected", {"reason": "decisions must be a non-empty map of id -> approved|rejected"}
    if not (isinstance(payload.get("reviewer"), str) and payload["reviewer"].strip()): return "rejected", {"reason": "reviewer missing"}
    try:
        exp = time.strptime(str(payload.get("expires")), "%Y-%m-%d")
    except ValueError:
        return "rejected", {"reason": "expires is not a YYYY-MM-DD date", "expires": payload.get("expires")}
    if payload.get("artifact_digest") != artifact_digest: return "rejected", {"reason": "attestation is for a different artifact", "attested": payload.get("artifact_digest")}
    if payload.get("release_digest") != release_digest: return "rejected", {"reason": "attestation is for a different platform release"}
    today = time.strptime(today, "%Y-%m-%d") if today else time.gmtime()
    if exp < today: return "rejected", {"reason": "attestation expired", "expires": payload.get("expires")}
    missing = [i for i in required_ids if i not in d]
    if missing: return "rejected", {"reason": f"attestation does not decide {missing}"}
    if any(d[i] == "rejected" for i in required_ids): return "rejected", {"decisions": d, "reviewer": payload.get("reviewer")}
    if not all(d[i] == "approved" for i in required_ids): return "rejected", {"reason": "every required evaluation must be explicitly approved", "decisions": d}
    return "approved", {"decisions": d, "reviewer": payload.get("reviewer"), "signed_at": payload.get("signed_at"), "expires": payload.get("expires")}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen"); k.add_argument("--out", required=True)
    s = sub.add_parser("sign"); s.add_argument("--key", required=True); s.add_argument("--artifact", required=True); s.add_argument("--release", required=True)
    s.add_argument("--decide", action="append", required=True); s.add_argument("--expires", required=True); s.add_argument("--reviewer", required=True); s.add_argument("--out", required=True)
    a = ap.parse_args()
    keygen(a.out) if a.cmd == "keygen" else sign(a)
