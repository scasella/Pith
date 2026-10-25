"""Negative suite for the generated monitor, frozen. Each stream must raise exactly the named alert;
the good stream must be silent. These are the reviewer's probes turned into obligations."""
import pathlib, subprocess, sys, threading, time, pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "gen" / "out"))
from monitor import Monitor, Shadow
import monitor as MON

P = "auth-service"
import hashlib, json
def chain(events):
    """Seal a raw stream the way a compliant adapter does (op ids assigned per operation: an op ends at op.committed);
    tests mutate AFTER sealing to show the chain catches it."""
    out, prev, op, n = [], "0" * 64, None, 0
    for ev in events:
        if op is None: n += 1; op = f"op{n}"
        ev = dict(ev, op_id=ev.get("op_id", op))
        if ev["type"] == "op.committed": op = None
        body = {k: v for k, v in ev.items() if k not in ("hash", "seq")}; body["prev_hash"] = prev
        h = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        out.append({**body, "hash": h, "seq": ev.get("seq")}); prev = h
    return out
def resealed(events):
    """Rehash a mutated stream so only semantic checks can catch it (hash validity is not semantic correctness)."""
    return chain([{k: v for k, v in e.items() if k not in ("hash", "prev_hash")} for e in events])
def created(a, limit, seq): return [{"type": "account.created", "account_id": a, "limit": limit, "producer": P, "seq": seq},
                                    {"type": "op.committed", "account_id": a, "request_id": None, "op": "create_account", "producer": P, "seq": seq + 1,
                                     "state_after": {"limit": limit, "posted": 0, "reserved": 0}}]
def decided(a, r, amt, avail, dec, seq): return {"type": "auth.decided", "account_id": a, "request_id": r, "amount": amt, "available_at_decision": avail, "decision": dec, "producer": P, "seq": seq}
def hold(a, r, amt, seq):   return {"type": "reservation.created", "account_id": a, "request_id": r, "amount": amt, "producer": P, "seq": seq}
def rel(a, r, seq):         return {"type": "reservation.released", "account_id": a, "request_id": r, "producer": P, "seq": seq}
def done(a, r, op, seq, limit=100, reserved=0, posted=0): return {"type": "op.committed", "account_id": a, "request_id": r, "op": op, "producer": P, "seq": seq, "state_after": {"limit": limit, "posted": posted, "reserved": reserved}}
def cap(a, r, amt, seq):    return {"type": "capture.posted", "account_id": a, "request_id": r, "amount": amt, "producer": P, "seq": seq}

GOOD = chain(created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=60),
        decided(1, 2, 60, 40, "DECLINED", 6), done(1, 2, "authorize", 7, reserved=60), rel(1, 1, 8), done(1, 1, "release", 9, reserved=0),
        decided(1, 3, 100, 100, "AUTHORIZED", 10), hold(1, 3, 100, 11), done(1, 3, "authorize", 12, reserved=100)] + created(2, 50, 13) +
       [decided(2, 1, 50, 50, "AUTHORIZED", 15), hold(2, 1, 50, 16), done(2, 1, "authorize", 17, limit=50, reserved=50)])   # request id 1 reused in account 2

def codes(stream): return sorted({a["code"] for a in Monitor().run(stream)["alerts"]})

def test_good_stream_is_silent_and_covers_both_branches():
    rep = Monitor().run(GOOD); assert rep["alerts"] == [] and rep["antecedents"]["P0"] >= 2 and rep["antecedents"]["P1"] >= 1

CASES = {
  "P1-obs":  created(1, 100, 1) + [decided(1, 1, 150, 100, "AUTHORIZED", 3), hold(1, 1, 150, 4), done(1, 1, "authorize", 5)],
  "P0-obs":  created(1, 100, 1) + [decided(1, 1, 100, 100, "DECLINED", 3), done(1, 1, "authorize", 4)],
  "P2-amount": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 1, 4), done(1, 1, "authorize", 5)],
  "COMPLETE-missing-reservation": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), done(1, 1, "authorize", 4)],
  "P2-obs|reservation-on-decline": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5),
                                     decided(1, 2, 60, 40, "DECLINED", 6), hold(1, 2, 60, 7), done(1, 2, "authorize", 8)],
  "R1-terminal": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5),
                 rel(1, 1, 6), done(1, 1, "release", 7), hold(1, 1, 60, 8)],
  "P2-obs":  created(1, 100, 1) + [hold(1, 9, 10, 3)],
  "P3-obs":  created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5), decided(1, 1, 60, 40, "DECLINED", 6)],
  "AVAIL-MISMATCH": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5), decided(1, 2, 10, 100, "AUTHORIZED", 6), hold(1, 2, 10, 7), done(1, 2, "authorize", 8)],
  "INV1-obs": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5), decided(1, 2, 60, 40, "AUTHORIZED", 6), hold(1, 2, 60, 7), done(1, 2, "authorize", 8)],
  "R1-unknown": created(1, 100, 1) + [rel(1, 5, 3), done(1, 5, "release", 4)],
  "COMPLETE-unterminated": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4)],
  # reviewer's streams
  "OP-composition|create-without-commit": [{"type": "account.created", "account_id": 1, "limit": 100, "producer": P, "seq": 1},
                                           decided(1, 1, 60, 100, "AUTHORIZED", 2), hold(1, 1, 60, 3), done(1, 1, "authorize", 4, reserved=60)],
  "OP-after-commit|duplicate-decline-commit": created(1, 100, 1) + [decided(1, 1, 150, 100, "DECLINED", 3), done(1, 1, "authorize", 4), dict(done(1, 1, "authorize", 5), op_id="op2")],
  "OP-composition|release-absorbed": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), rel(1, 1, 5), done(1, 1, "authorize", 6, reserved=0)],
  "C-obs|capture-without-hold": created(1, 100, 1) + [cap(1, 7, 10, 3), done(1, 7, "capture", 4, posted=10)],
  "C-amount": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=60), cap(1, 1, 61, 6), done(1, 1, "capture", 7, posted=61)],
  "C-obs|double-capture": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=60), cap(1, 1, 60, 6), done(1, 1, "capture", 7, posted=60), cap(1, 1, 60, 8), done(1, 1, "capture", 9, posted=120)],
  "R1-unknown|release-after-capture": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=60), cap(1, 1, 60, 6), done(1, 1, "capture", 7, posted=60), rel(1, 1, 8), done(1, 1, "release", 9, posted=60)],
  "STATE|capture-not-reflected": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=60), cap(1, 1, 60, 6), done(1, 1, "capture", 7, posted=0)],
  "OP-interleaved": created(1, 100, 1) + [dict(decided(1, 1, 60, 100, "AUTHORIZED", 3), op_id="opA"), dict(decided(1, 2, 10, 100, "AUTHORIZED", 4), op_id="opB"),
                    dict(hold(1, 1, 60, 5), op_id="opA"), dict(done(1, 1, "authorize", 6, reserved=60), op_id="opA"), dict(hold(1, 2, 10, 7), op_id="opB"), dict(done(1, 2, "authorize", 8, reserved=70), op_id="opB")],
  "PRODUCER": created(1, 100, 1) + [dict(decided(1, 1, 60, 100, "AUTHORIZED", 3), producer="other"), hold(1, 1, 60, 4), done(1, 1, "authorize", 5)],
  "ORDER": created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 2), hold(1, 1, 60, 4), done(1, 1, "authorize", 5)],
  "DUP-ACCOUNT": created(1, 100, 1) + created(1, 100, 3),
  "P2-duplicate-hold": created(1, 100, 1) + [decided(1, 1, 30, 100, "AUTHORIZED", 3), hold(1, 1, 30, 4), hold(1, 1, 30, 5), done(1, 1, "authorize", 6)],
}
@pytest.mark.parametrize("code,stream", CASES.items())
def test_named_violation_is_detected(code, stream):
    code = code.split("|")[0]
    got = codes(resealed(stream))                     # rehashed: a valid chain must not hide a semantic violation
    assert code in got, f"expected {code}, got {got}"

def test_altered_event_breaks_the_chain():
    evs = [dict(e) for e in GOOD]; evs[2]["amount"] = 61
    assert "CHAIN" in codes(evs)

def test_state_after_must_match_reconstruction():
    bad = created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=0)]
    assert "STATE" in codes(resealed(bad))

def test_truncated_tail_is_not_detected_by_chain_alone():
    """A valid prefix ending inside an operation is caught by COMPLETE-unterminated; a prefix ending AT a commit boundary
    is only caught with a watermark."""
    assert "COMPLETE-unterminated" in codes(GOOD[:4])
    assert codes(GOOD[:5]) == []                                                   # ends at a commit: silent without a watermark
    assert "INCOMPLETE" in sorted({a["code"] for a in Monitor().run(GOOD[:5], expected_last_seq=GOOD[-1]["seq"])["alerts"]})

GOOD_CAPTURE = chain(created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=60),
    cap(1, 1, 60, 6), done(1, 1, "capture", 7, posted=60), decided(1, 2, 40, 40, "AUTHORIZED", 8), hold(1, 2, 40, 9), done(1, 2, "authorize", 10, reserved=40, posted=60),
    decided(1, 3, 1, 0, "DECLINED", 11), done(1, 3, "authorize", 12, reserved=40, posted=60)])

def test_capture_stream_is_silent_and_available_shrinks_by_posted():
    rep = Monitor().run(GOOD_CAPTURE); assert rep["alerts"] == [], rep["alerts"]

def test_same_request_id_in_two_accounts_is_not_a_duplicate():
    assert "P3-obs" not in codes(GOOD)


# ---- shadow mode: the monitor plus the offline oracle (obligations/boundary/oracle.py) on a live feed -------------------------------------
import yaml
from http.server import BaseHTTPRequestHandler, HTTPServer

def shadow_of(stream, **kw):
    sh = Shadow(**kw)
    for ev in stream: sh.feed(ev)                                                  # feed never raises: asserted by every test that reaches here
    return sh

# an authorization the stream says was AUTHORIZED although the amount exceeds what was available: the monitor alerts (P1-obs) and the oracle
# (the verified core, replayed) answers DECLINED to the same operation
OVER_GRANT = resealed(created(1, 100, 1) + [decided(1, 1, 150, 100, "AUTHORIZED", 3), hold(1, 1, 150, 4), done(1, 1, "authorize", 5, reserved=150)])
# a resealed stream (valid hashes) whose op.committed declares a state the events do not produce: the monitor alerts STATE, the oracle disputes state_after,
# and the answer itself (what the client was told) is the one the contract requires
WRONG_STATE = resealed(created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4), done(1, 1, "authorize", 5, reserved=0)])

def test_shadow_is_silent_on_a_good_stream_and_reconstructs_every_operation():
    for stream, n in ((GOOD, 7), (GOOD_CAPTURE, 5)):
        sh = shadow_of(stream); assert sh.mode == "oracle" and sh.divergences == [] and sh.errors == 0 and sh.dropped == 0, sh.summary()
        assert len(sh.operations) == n and sh.events == len(stream)
        assert [o["action"] for o in sh.operations][:2] == ["create_account", "authorize"] and all(o["observed"].get("replayed", False) is False for o in sh.operations)

def test_shadow_records_an_over_grant_as_a_divergence_without_raising(tmp_path):
    log = tmp_path / "divergence.jsonl"; sh = shadow_of(OVER_GRANT, out=str(log), release="r" * 64, artifact="a" * 64)
    assert sh.errors == 0 and len(sh.divergences) == 1
    rec = sh.divergences[0]
    assert rec["format"] == "pith.divergence/v1" and rec["alert"] == "P1-obs" and rec["diverged_at"] == 1 and rec["mode"] == "oracle" and not rec["lossy"]
    assert rec["release_digest"] == "r" * 64 and rec["artifact_digest"] == "a" * 64 and "P1" in rec["records"] and "P0" in rec["records"]
    assert [o["action"] for o in rec["operations"]] == ["create_account", "authorize"]
    d = rec["disagreement"]; assert d["fields"] == ["decision", "state_after"] and d["observed"]["decision"] == "AUTHORIZED" and d["expected"]["decision"] == "DECLINED"
    assert rec["operations"][1]["args"] == {"account": 1, "request": 1, "amount": 150} and rec["operations"][1]["expected"] == d["expected"]
    lines = [json.loads(l) for l in log.read_text().splitlines()]; assert len(lines) == 1 and lines[0] == json.loads(json.dumps(rec))

def test_shadow_records_a_resealed_state_the_oracle_disputes():
    sh = shadow_of(WRONG_STATE); assert sh.errors == 0 and len(sh.divergences) == 1
    rec = sh.divergences[0]; d = rec["disagreement"]
    assert rec["alert"] == "STATE" and "EventContract" in rec["records"] and rec["diverged_at"] == 1
    assert d["fields"] == ["state_after"] and d["expected"] == d["observed"]                 # the answer agrees; only the committed state is disputed
    assert d["state_after"]["declared"]["reserved"] == 0 and d["state_after"]["oracle"]["reserved"] == 60

def test_shadow_is_monitor_only_when_the_oracle_cannot_be_loaded():
    sh = shadow_of(OVER_GRANT, root="/nonexistent/release"); assert sh.mode == "monitor-only" and sh.oracle_error and sh.errors == 0
    assert sh.summary()["mode"] == "monitor-only" and len(sh.divergences) == 1
    rec = sh.divergences[0]; assert rec["alert"] == "P1-obs" and rec["mode"] == "monitor-only" and rec["disagreement"] is None and rec["diverged_at"] == 1

def test_shadow_with_a_sound_oracle_but_a_silent_monitor_still_records_the_disagreement():
    class Liar:                                                                       # an oracle that disagrees with a stream the monitor accepts
        def step(self, s): return {"id": s["args"].get("account"), "limit": -1} if s["action"] == "create_account" else {"status": 500}
    sh = shadow_of(GOOD[:2], oracle=Liar()); assert sh.monitor.alerts == [] and sh.mode == "oracle" and len(sh.divergences) == 1
    assert sh.divergences[0]["alert"] == "ORACLE-DISAGREES" and sh.divergences[0]["disagreement"]["fields"] == ["limit"]

def test_shadow_survives_failing_listeners_oracles_and_logs(tmp_path):
    def boom(rec): raise RuntimeError("listener failed")
    class Broken:
        def step(self, s): raise RuntimeError("oracle failed")
    seen = []
    sh = shadow_of(OVER_GRANT, listeners=[boom, seen.append]); assert len(sh.divergences) == 1 and seen == sh.divergences and sh.errors == 1       # raised nothing, counted
    sh = shadow_of(GOOD, oracle=Broken()); assert sh.errors >= 1 and sh.events == len(GOOD) and "RuntimeError" in sh.last_error                          # monitor still ran
    sh = shadow_of(OVER_GRANT, out=str(tmp_path)); assert len(sh.divergences) == 1 and sh.errors == 1                                                   # a log that cannot be written
    sh = Shadow(); sh.feed(None); sh.feed("not an event"); sh.feed({"type": "auth.decided"}); assert sh.errors >= 2 and "MALFORMED-EVENT" in sh.summary()["alerts"]

def test_attach_enqueues_on_a_bounded_queue_and_never_blocks_the_caller():
    sh = Shadow(queue_size=2); gate = threading.Event(); real = sh.feed
    sh.feed = lambda ev: (gate.wait(5), real(ev))                                      # a slow consumer: the drain thread is stuck on its first event
    host = []; emit = sh.attach(host.append); t0 = time.time()
    for ev in GOOD: emit(ev)
    assert time.time() - t0 < 1.0 and host == GOOD                                     # the caller was not held up and the host's emit ran for every event
    assert sh.dropped >= len(GOOD) - 3 > 0, sh.dropped                                 # what did not fit was counted, not waited for
    gate.set(); assert sh.flush(5) and sh.errors == 0
    sh.feed(GOOD[-1]); assert sh.divergences and all(d["lossy"] for d in sh.divergences)   # an event after the gap breaks the chain: the record says the reconstruction missed events

def test_attach_feeds_every_event_in_order_and_adds_nothing_that_raises():
    host = []; sh = Shadow(); emit = sh.attach(lambda ev: host.append(ev) or "ok")
    assert [emit(ev) for ev in OVER_GRANT] == ["ok"] * len(OVER_GRANT) and sh.flush(5)
    assert sh.dropped == 0 and sh.errors == 0 and len(sh.divergences) == 1 and sh.divergences[0]["alert"] == "P1-obs"
    sh2 = Shadow(oracle=type("B", (), {"step": lambda self, s: 1 / 0})()); emit2 = sh2.attach(lambda ev: None)
    for ev in GOOD: emit2(ev)                                                          # an oracle that fails inside the drain thread never reaches the caller
    assert sh2.flush(5) and sh2.errors >= 1
    def failing_host(ev): raise OSError("the host's own failure")
    sh3 = Shadow(); wrapped = sh3.attach(failing_host)
    with pytest.raises(OSError): wrapped(GOOD[0])                                      # the host's exception is the host's: propagated unchanged, nothing queued
    assert sh3.flush(5) and sh3.events == 0

def test_a_shadow_that_keeps_finding_the_same_defect_bounds_its_log(tmp_path):
    stream = created(1, 1000, 1)
    for i in range(1, 8): stream += [decided(1, i, 150, 100, "AUTHORIZED", 2 * i + 1), done(1, i, "authorize", 2 * i + 2)]        # seven authorizations, each over what was available
    sh = shadow_of(resealed(stream), out=str(tmp_path / "l.jsonl"), max_records=3)
    assert len(sh.divergences) == 3 and sh.suppressed > 0 and len((tmp_path / "l.jsonl").read_text().splitlines()) == 3

def test_an_operation_that_never_commits_is_a_divergence_at_the_end_of_the_stream():
    sh = shadow_of(chain(created(1, 100, 1) + [decided(1, 1, 60, 100, "AUTHORIZED", 3), hold(1, 1, 60, 4)])); assert sh.divergences == []
    sh.close(); assert [d["alert"] for d in sh.divergences] == ["COMPLETE-unterminated"] and sh.divergences[0]["diverged_at"] is None

def test_records_name_contract_records_the_pack_declares():
    declared = {c["id"] for c in yaml.safe_load((ROOT / "pack.yaml").read_text())["contracts"]}
    named = {r for v in list(MON.RECORDS.values()) + list(MON.FIELD_RECORDS.values()) for r in v}
    assert named <= declared, sorted(named - declared)

class Feed(BaseHTTPRequestHandler):
    events = []
    def log_message(self, *a): pass
    def do_GET(self):
        since = int(self.path.split("since=")[1]) if "since=" in self.path else 0
        data = json.dumps([e for e in self.events if (e.get("seq") or 0) > since]).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

def serve_events(events):
    Feed.events = events; srv = HTTPServer(("127.0.0.1", 0), Feed); threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"

def test_sidecar_reads_the_feed_of_a_service_in_a_separate_process(tmp_path, capsys):
    srv, url = serve_events(list(GOOD))
    try:
        log = tmp_path / "good.jsonl"
        assert MON.main(["shadow", "--events", url, "--out", str(log), "--once"]) == 0 and not log.exists()
        assert json.loads(capsys.readouterr().out.splitlines()[-1])["events"] == len(GOOD)
        Feed.events = list(OVER_GRANT); log = tmp_path / "bad.jsonl"
        r = subprocess.run([sys.executable, "-I", str(ROOT / "gen" / "out" / "monitor.py"), "shadow", "--events", url, "--out", str(log), "--once",
                            "--release", "r" * 64, "--artifact", "a" * 64], capture_output=True, text=True, timeout=60)
        assert r.returncode == 1, r.stderr                                             # a divergence was recorded
        summary = json.loads(r.stdout.splitlines()[-1]); assert summary["mode"] == "oracle" and summary["divergences"] == 1 and summary["errors"] == 0
        recs = [json.loads(l) for l in log.read_text().splitlines()]
        assert len(recs) == 1 and recs[0]["alert"] == "P1-obs" and recs[0]["release_digest"] == "r" * 64 and recs[0]["artifact_digest"] == "a" * 64
    finally:
        srv.shutdown()

def test_sidecar_reports_a_service_it_cannot_reach(tmp_path, capsys):
    assert MON.main(["shadow", "--events", "http://127.0.0.1:9", "--out", str(tmp_path / "x"), "--once"]) == 2
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["fetch_errors"] == 1
