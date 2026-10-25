"""validation/test_packet.py — unit tests for gate/packet.py (failure categories, counterexamples, the packet) and the
manifest `include` rules in gate/workspace.py, on canned tool output. CI runs them; the end-to-end runs are
validation/packets.py and validation/judge_wrong.py.

    python3 -m pytest validation/test_packet.py -q
"""
import json, pathlib, sys
import jsonschema, pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gate"))
import packet as PT, workspace as W

TLC = """Error: Invariant Bounded is violated.
Error: The behavior up to this point is:
State 1: <Initial predicate>
/\\ tally = 0
State 2: <Request line 9>
/\\ tally = 1
"""
HYP = """____ test_service_agrees ____
E   AssertionError
Falsifying example: test_service_agrees(
    ops=[('book', 1, 0, 60), ('book', 1, 60, 120)],
)
"""
PYTEST = """=================================== FAILURES ===================================
______ test_the_bound_holds ______

svc = <x>

    def test_the_bound_holds(svc):
        \"\"\"Contract: T1.\"\"\"
        c = svc.client
>       assert 4 == 3
E       assert 4 == 3
harness/lifecycle.py:26: AssertionError
=========================== short test summary info ============================
FAILED harness/lifecycle.py::test_the_bound_holds
"""


def spec(**kw): return {"id": "c", "kind": "command", **kw}


def test_categories_in_their_order_of_precedence():
    assert PT.classify("x", "command", spec(), None, "", {}, exc="TimeoutExpired")[0] == "infrastructure"
    assert PT.classify("x", "tlc", spec(tools=["tlc"]), None, "", {"tlc": "unknown"})[0] == "toolchain_unavailable"
    assert PT.classify("x", "command", spec(), None, "sh: 1: dafny: not found", {})[0] == "toolchain_unavailable"
    assert PT.classify("x", "command", spec(failure_category="not_exercised"), None, "boom", {})[0] == "not_exercised"
    assert PT.classify("x", "command", spec(about="release"), None, "boom", {})[0] == "infrastructure"
    assert PT.classify("x", "adapter", spec(kind="adapter"), "not_exercised", "", {})[0] == "not_exercised"
    assert PT.classify("x", "files_present", spec(kind="files_present"), None, "", {})[0] == "evidence_missing"
    assert PT.classify("x", "command", spec(), None, "AssertionError", {})[0] == "violation"


def test_evaluator_checks():
    assert PT.classify("frozen files intact", "evaluator", None, None, "", {})[0] == "contract_change"
    assert PT.classify("manifest allowlisted", "evaluator", None, None, "", {})[0] == "contract_change"
    assert PT.classify("external release pin", "evaluator", None, None, "", {})[0] == "infrastructure"


def test_a_declared_tool_that_is_available_is_not_blamed():
    assert PT.classify("x", "tlc", spec(tools=["tlc"]), None, "Invariant X is violated", {"tlc": "TLC2 Version 2.19"})[0] == "violation"


def test_counterexamples_come_from_the_tool_that_found_them():
    assert PT.counterexample(TLC, "tlc")["source"].startswith("tlc") and "tally = 1" in PT.counterexample(TLC, "tlc")["text"]
    assert PT.counterexample(HYP, "command")["source"].startswith("hypothesis") and "('book', 1, 60, 120)" in PT.counterexample(HYP, "command")["text"]
    cx = PT.counterexample(PYTEST, "command")
    assert cx["source"].startswith("pytest") and cx["text"].startswith("test test_the_bound_holds") and "> " in cx["text"] and "Contract: T1" in cx["text"]
    assert PT.counterexample("nothing useful", "command") is None


def test_the_packet_names_the_records_the_failing_test_names():
    P = {"pack": {"id": "p", "version": "1"}, "policy_dirs": ["harness"], "candidate": {"owned_dirs": ["service"], "manifest_allowlist": ["name"]},
         "statuses": {"s": {"rule": "all_pass", "ready": {"startswith": "passed"}}}, "completion_status": "s",
         "checks": [{"id": "life", "kind": "command", "command": "{pytest} harness/lifecycle.py"}], "pytest": "{python} -m pytest -q",
         "contracts": [{"id": "T1", "intent": "bound", "verified_by": ["life"]}, {"id": "T2", "intent": "exact", "verified_by": ["life"]}]}
    rec = {"id": "life", "check": "lifecycle", "kind": "command", "result": "fail", "blocking": True, "why": PYTEST, "category": "violation", "category_basis": "b", "establishes": []}
    pk = PT.build({"pack": {"id": "p", "version": "1"}, "artifact_digest": "a" * 64, "release_ready_missing": ["s"], "s": "refused"}, [rec], P,
                  "local (advisory)", "/c", "/c", "/ev", {}, "r" * 64)
    jsonschema.validate(pk, json.loads((ROOT / "gate/schemas/task-packet.schema.json").read_text()))
    f = pk["first_failure"]
    assert pk["state"] == "refused" and [c["id"] for c in f["contracts"]] == ["T1"] and f["contracts_basis"] == "named by the failing output"
    assert pk["rerun"]["focused"].endswith("-k test_the_bound_holds") and "s" not in pk["not_yours"]
    assert "Task packet: REFUSED" in PT.markdown(pk)


def test_include_rules(tmp_path):
    (tmp_path / "src").mkdir(); (tmp_path / "kernel").mkdir()
    assert W.include_problems(["src"], ["gate", "kernel"], tmp_path) == []
    for bad in (["../x"], ["/etc"], ["kernel"], ["kernel/x"], ["gate"], [".git"], ["missing"], "src", [""]):
        assert W.include_problems(bad, ["gate", "kernel"], tmp_path), bad


# ================================================================= distilled packets (v0.13.0, docs/rfc/0007 § 5)
import re, subprocess, textwrap
import shrink as SH

SCHEMA = json.loads((ROOT / "gate/schemas/task-packet.schema.json").read_text())
HOST = [r"/Users/", r"/home/", r"/private/", r"/var/folders/", r"/tmp/", r"/opt/", r'File "', r"Traceback", r"\bat \S.*\(\S+:\d+:\d+\)", r"object at 0x"]


def leaks(o, words=()):
    """Everything a distilled packet must not contain: a host path, a stack frame, a repr with a memory address, a code identifier."""
    s = json.dumps(o) if not isinstance(o, str) else o
    return [p for p in HOST if re.search(p, s)] + [w for w in words if re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", s)]


def test_redact_removes_absolute_paths_of_every_host_kind():
    for path in ("/Users/alice/work/pith/obligations/service/lifecycle.py", "/private/var/folders/t6/abc/T/judged-j12i37od", "/var/folders/t6/abc/T/judged-j12i37od",
                 "/home/runner/work/Pith/Pith/gate/app_gate.py", "/tmp/pytest-of-runner/pytest-0/test_x0", "/opt/hostedtoolcache/Python/3.12/x64/bin/python",
                 "file:///Users/alice/ui/index.js", "C:\\Users\\alice\\AppData\\Local\\Temp\\x"):
        t = PT.redact(f"cannot open {path} (twice: '{path}')", set())
        assert "«path»" in t and not leaks(t) and "alice" not in t and "runner" not in t and "judged-" not in t, (path, t)
    assert PT.redact("limit 100, request 7", set()) == "limit 100, request 7", "ordinary text is left alone"


def test_redact_removes_python_and_node_frames():
    py = 'Traceback (most recent call last):\n  File "/Users/a/judge/harness.py", line 12, in check_it\n    assert secret_total == 3\nAssertionError: 4 != 3\nobligations/service/lifecycle.py:72: AssertionError'
    t = PT.redact(py, {"check_it", "secret_total"})
    assert t == "AssertionError: 4 != 3", t
    node = "Error: boom\n    at Object.<anonymous> (/home/u/app/x.js:10:5)\n    at async Module._compile (node:internal/modules/cjs/loader:1256:14)\n    at run (/home/u/app/y.mjs:3:9)\n    at /home/u/app/z.js:1:1"
    t = PT.redact(node, set())
    assert t == "Error: boom" and not leaks(t), t


def test_redact_drops_the_source_pytest_echoes_and_masks_the_harness_identifiers():
    code = {"test_the_bound_holds", "svc"}
    t = PT.redact(PYTEST, code)
    assert "def " not in t and "svc.client" not in t and "Contract: T1" not in t and "lifecycle.py:26" not in t, t
    assert "assert 4 == 3" in t and "«code»" in t and "test_the_bound_holds" not in t, t       # the assertion's own words stay, the harness's names do not
    assert PT.redact("the library gave retry_after_for(key) = 3", {"retry_after_for"}) == "the library gave «code»(key) = 3"
    assert PT.redact("a «code» b" + " «code»" * 3, set()).count("«code»") >= 1
    assert len(PT.redact("x " * 2000, set(), limit=100)) <= 100


def test_code_shaped_names_are_the_ones_only_code_produces():
    for w in ("retry_not_released", "check_it", "camelCase", "limiter2", "INV1", "x_y"):
        assert PT.code_shaped(w), w
    for w in ("found", "rows", "Service", "ab", "__init__", "release", "replayed", "AUTHORIZED"):
        assert not PT.code_shaped(w), w


def test_a_counterexample_line_is_one_line_in_the_harnesss_words_and_survives_the_failure_output():
    steps = [{"step": 1, "action": "create", "args": {"account": 1, "limit": 100}, "observed": {"id": 1, "limit": 100}},
             {"step": 2, "action": "release", "args": {"account": 1, "request": 1}, "observed": {"released": False}, "expected": {"released": True}}]
    line = PT.cx_line(steps, expected={"released": True}, observed={"released": False}, violated=["Receipts"], diverged_at=1, replayable=True, source="harness")
    assert "\n" not in line and line.startswith("pith-counterexample: ")
    output = f"E   AssertionError: {line}\nE   assert {{'released': False}} == {{'released': True}}\nharness.py:9: AssertionError\n1 failed in 0.1s\n"
    X = PT.structured({"why": output, "kind": "command", "check": "life"}, {}, {}, ROOT)
    assert X["steps"] == steps and X["violated"] == ["Receipts"] and X["source"] == "harness" and X["diverged_at"] == 1 and X["replayable"] is True
    assert PT.structured({"why": "E   AssertionError: pith-counterexample: {not json}", "kind": "command", "check": "life"}, {}, {}, ROOT) is None


def test_a_trace_is_cut_after_its_first_diverging_step_and_says_so():
    steps = [{"step": i, "action": "tick", "args": {"n": i}, "observed": {"n": i}} for i in range(1, 7)]
    X = PT.shrink_trace({"steps": list(steps), "diverged_at": 2}, {}, ROOT)
    assert X["steps"] == steps[:3] and X["shrunk"] == {"from_steps": 6, "to_steps": 3, "against": "truncated after the first diverging step"}
    Y = PT.shrink_trace({"steps": list(steps), "diverged_at": 5}, {}, ROOT)
    assert Y["steps"] == steps and "shrunk" not in Y, "the last step diverging: nothing to cut and no oracle declared, so nothing is claimed"
    assert PT.shrink_trace({"source": "x"}, {}, ROOT) == {"source": "x"}


TINY_ORACLE = textwrap.dedent('''\
    import json, sys
    store, out = {}, []
    for s in json.load(sys.stdin)["steps"]:
        a = s["args"]
        if s["action"] == "put": store[a["k"]] = a["v"]; out.append({"ok": True})
        else: out.append({"v": store.get(a["k"])})
    print(json.dumps({"outcomes": out}))
    ''')


def tiny_oracle(tmp_path):
    f = tmp_path / "oracle.py"; f.write_text(TINY_ORACLE)
    return f"{sys.executable} {f}"


def put(k, v): return {"action": "put", "args": {"k": k, "v": v}}
def get(k): return {"action": "get", "args": {"k": k}}


def test_ddmin_finds_a_one_minimal_sequence_against_an_offline_oracle(tmp_path):
    cmd = tiny_oracle(tmp_path)
    steps = [put("a", 1), put("b", 2), put("a", 3), put("c", 4), put("d", 5), get("a")]
    assert SH.oracle(cmd, steps) == [{"ok": True}] * 5 + [{"v": 3}]
    want = SH.oracle(cmd, steps)[-1]
    small, calls = SH.ddmin(steps, lambda s: SH.oracle(cmd, s)[-1] == want, keep_last=True)
    assert small == [put("a", 3), get("a")] and calls > 0
    for i in range(len(small) - 1):                                                   # 1-minimal: dropping any single step loses the answer
        assert SH.oracle(cmd, small[:i] + small[i + 1:])[-1] != want
    assert SH.ddmin([get("a")], lambda s: True, keep_last=True)[0] == [get("a")]
    with pytest.raises(ValueError):
        SH.ddmin(steps, lambda s: False)
    with pytest.raises(RuntimeError):
        SH.oracle(f"{sys.executable} -c 'import sys; sys.exit(3)'", steps)


def test_the_packet_shrinks_against_the_packs_oracle_and_never_runs_the_candidate(tmp_path):
    P = {"traces": {"oracle": tiny_oracle(tmp_path)}}
    steps = [dict(put("a", 1), step=1, observed={"ok": True}), dict(put("b", 2), step=2), dict(put("a", 3), step=3), dict(put("c", 4), step=4), dict(get("a"), step=5, observed={"v": 1})]
    X = PT.shrink_trace({"steps": steps, "diverged_at": 4, "replayable": True}, P, tmp_path)
    # the kept steps are renumbered and the diverging one is the last (the original numbers would point at steps that are gone)
    assert [s["step"] for s in X["steps"]] == [1, 2] and X["diverged_at"] == 1 and X["shrunk"]["against"] == "oracle" and (X["shrunk"]["from_steps"], X["shrunk"]["to_steps"]) == (5, 2)
    assert X["steps"][-1]["observed"] == {"v": 1}, "the candidate's observed answers are kept on the steps that stay"
    Z = PT.shrink_trace({"steps": steps, "diverged_at": 4, "replayable": False}, P, tmp_path)
    assert len(Z["steps"]) == 5 and "shrunk" not in Z, "a trace the oracle cannot replay is not shrunk against it"
    broken = PT.shrink_trace({"steps": steps, "diverged_at": 4, "replayable": True}, {"traces": {"oracle": f"{sys.executable} -c 'import sys; sys.exit(2)'"}}, tmp_path)
    assert len(broken["steps"]) == 5 and any("not shrunk against the oracle" in n for n in broken["notes"])


TLC_FULL = """TLC2 Version 2.19 of 08 August 2024
Running breadth-first search Model-Checking with fp 63 and seed 1 with 1 worker on 4 cores
Parsing file /Users/alice/work/design/MC.tla
Error: Invariant Bounded is violated.
Error: The behavior up to this point is:
State 1: <Initial predicate>
/\\ tally = 0
/\\ log = <<>>
State 2: <Request line 9, col 9 to line 12, col 20 of module Design>
/\\ tally = 1
/\\ log = <<"a">>
State 3: <Request line 9, col 9 to line 12, col 20 of module Design>
/\\ tally = 2
/\\ log = <<"a", "b">>
"""


def test_a_model_checkers_trace_is_read_as_actions_and_values_without_modules_or_lines():
    steps = PT._tlc_trace(TLC_FULL[TLC_FULL.find("The behavior up to this point is:"):])
    assert [(s["step"], s["action"]) for s in steps] == [(1, "initial state"), (2, "Request"), (3, "Request")]
    assert steps[2]["state"] == {"tally": "2", "log": '<<"a", "b">>'}
    X = PT.structured({"why": TLC_FULL, "kind": "tlc", "check": "design.safety"}, {}, {}, ROOT)
    assert X["violated_property"] == "Bounded" and len(X["trace"]) == 3 and X["source"].startswith("model checker")
    assert not leaks(json.dumps(X["trace"])) and "line 9" not in json.dumps(X["trace"]) and "module" not in json.dumps(X["trace"])
    assert PT.structured({"why": "nothing to see", "kind": "command", "check": "x"}, {}, {}, ROOT) is None


def delivery_claims():
    return {"delivery_detail": {"workflows": {"W1": {"ok": True, "evidence": ["fine"]}, "W3": {"ok": False, "evidence": ["opened the page; then clicked Decline; expected DECLINED, saw ERROR"]}}}}


def test_a_failed_workflow_is_a_trace_of_what_the_page_did():
    P = {"checks": [{"id": "delivery", "kind": "adapter", "claims_key": "delivery_detail"}]}
    X = PT.structured({"why": "", "kind": "adapter", "check": "delivery"}, delivery_claims(), P, ROOT)
    assert X["violated"] == ["W3"] and [s["action"] for s in X["trace"]] == ["opened the page", "clicked Decline", "expected DECLINED, saw ERROR"]
    assert all(s["workflow"] == "W3" for s in X["trace"])


def synthetic_release(tmp_path):
    """A policy root: a pack.yaml, an intent document, a harness module with identifiers of its own."""
    root = tmp_path / "release"; (root / "harness").mkdir(parents=True); (root / "gate").mkdir()
    (root / "INTENT.md").write_text("A hold reserves an amount of the limit; a release gives it back. Receipts answer retries.\n")
    (root / "harness/checks.py").write_text("def replay_secret_trace(client, hold_ledger):\n    sentinel_total = 3\n    return client, hold_ledger, sentinel_total\n\nclass JudgeOnly:\n    pass\n")
    P = {"pack": {"id": "p.demo", "version": "1", "intent": "INTENT.md"}, "policy_dirs": ["harness"], "candidate": {"owned_dirs": ["service"], "manifest_allowlist": ["name"]},
         "statuses": {"s": {"rule": "all_pass", "ready": {"startswith": "passed"}}}, "completion_status": "s", "pytest": "{python} -m pytest -q",
         "traces": {"oracle": tiny_oracle(tmp_path)},
         "checks": [{"id": "life", "kind": "command", "command": "{pytest} harness/checks.py", "claims_key": None}],
         "contracts": [{"id": "Receipts", "intent": "A retry returns its receipt.", "verified_by": ["life"], "semantics": {"python": "harness/checks.py replay_secret_trace", "markdown": "INTENT.md"}}]}
    import yaml
    (root / "pack.yaml").write_text(yaml.safe_dump(P))
    return root, P


def synthetic_evidence(tmp_path, root, P, why):
    rec = {"id": "life", "check": "lifecycle harness", "kind": "command", "result": "fail", "blocking": True, "why": why, "category": "violation", "category_basis": "b", "establishes": []}
    claims = {"pack": {"id": "p.demo", "version": "1"}, "artifact_digest": "a" * 64, "release_ready_missing": [], "checks": [rec], "s": "refused"}
    pk = PT.build(claims, [rec], P, "authoritative", "/Users/alice/candidate", str(root), str(tmp_path / "ev"), {}, "r" * 64)
    ev = tmp_path / "ev"; ev.mkdir(); (ev / "task-packet.json").write_text(json.dumps(pk)); (ev / "app-claims.json").write_text(json.dumps(claims))
    return ev, pk


def failing_output(root):
    steps = [put("a", 1), put("b", 2), put("a", 3), put("c", 4), get("a")]
    steps = [dict(s, step=i + 1, observed={"ok": True}) for i, s in enumerate(steps)]; steps[-1]["observed"] = {"v": 1}
    line = PT.cx_line(steps, expected={"v": 3}, observed={"v": 1}, violated=["Receipts"], diverged_at=4, replayable=True, source="black-box harness")
    return (f'Traceback (most recent call last):\n  File "/Users/alice/work/pith/harness/checks.py", line 40, in replay_secret_trace\n    assert sentinel_total == 3\n'
            f"E   AssertionError: {line}\nE   assert {{'v': 1}} == {{'v': 3}}\n{root}/harness/checks.py:40: AssertionError\n"
            f"/private/var/folders/t6/T/judged-abc/service/app.py:12: in hold_ledger\nFAILED /private/var/folders/t6/T/judged-abc::replay_secret_trace\n1 failed in 0.2s\n")


def test_distill_reads_the_counterexample_shrinks_it_and_leaks_nothing(tmp_path):
    root, P = synthetic_release(tmp_path)
    ev, pk = synthetic_evidence(tmp_path, root, P, failing_output(root))
    r = subprocess.run([sys.executable, str(ROOT / "gate/packet.py"), "distill", str(ev), "--policy-from", str(root), "--json"], capture_output=True, text=True, cwd="/")
    assert r.returncode == 0, r.stderr
    D = json.loads(r.stdout); assert D == json.loads((ev / "task-packet.distilled.json").read_text()) and (ev / "TASK.distilled.md").exists()
    jsonschema.validate(D, SCHEMA)
    cx = D["first_failure"]["counterexample"]
    assert D["disclosure"] == "redacted" and cx["redacted"] is True and cx["violated"] == ["Receipts"] and cx["expected"] == {"v": 3} and cx["observed"] == {"v": 1}
    assert [s["action"] for s in cx["trace"]] == ["put", "get"] and cx["trace"][0]["args"] == {"k": "a", "v": 3}
    assert cx["shrunk"]["against"] == "oracle" and (cx["shrunk"]["from_steps"], cx["shrunk"]["to_steps"]) == (5, 2)
    assert [c["id"] for c in D["first_failure"]["contracts"]] == ["Receipts"]
    assert not leaks(D, ["replay_secret_trace", "sentinel_total", "hold_ledger", "JudgeOnly", "alice"]) and not leaks((ev / "TASK.distilled.md").read_text(), ["replay_secret_trace"])
    # with a structured counterexample, `why` keeps only the assertion's own words: no counterexample line, banner or FAILED summary
    w = D["first_failure"]["why"]
    assert "pith-counterexample" not in w and "FAILED" not in w and "====" not in w and "harness/" not in w, w
    assert pk["first_failure"]["why"].count("/Users/alice") >= 1, "the original packet is unchanged: it still holds the host paths"
    assert "/Users" not in D["rerun"]["full"] and D["evidence"] == {"claims": "app-claims.json", "records": "evidence.json"}


def test_the_domain_words_a_pack_uses_are_not_masked_but_its_code_identifiers_are(tmp_path):
    root, P = synthetic_release(tmp_path)
    allowed, code = PT.vocabulary(root, P)
    assert {"reserves", "limit", "Receipts", "retries", "life"} <= allowed
    assert {"replay_secret_trace", "hold_ledger", "sentinel_total"} <= code and "JudgeOnly" in code | allowed
    assert "limit" not in code and "client" not in code, "a plain word is prose wherever it is used"
    P2 = dict(P, packet={"vocabulary": ["extra.md"]}); (root / "extra.md").write_text("replay_secret_trace is documented here\n")
    allowed2, code2 = PT.vocabulary(root, P2)
    assert "replay_secret_trace" in allowed2 and "replay_secret_trace" not in code2, "a word the pack's own documents use is allowed"


def test_a_distilled_packet_without_a_failure_or_with_only_a_pytest_diff_is_still_schema_valid(tmp_path):
    root, P = synthetic_release(tmp_path)
    ev, _ = synthetic_evidence(tmp_path, root, P, PYTEST)
    D = PT.distill(json.loads((ev / "task-packet.json").read_text()), json.loads((ev / "app-claims.json").read_text()), P, root)
    jsonschema.validate(D, SCHEMA)
    cx = D["first_failure"]["counterexample"]
    assert cx["redacted"] is True and "assert 4 == 3" in cx["text"] and not leaks(D) and "trace" not in cx
    done = {"format": PT.FORMAT, "pack": {"id": "p", "version": "1"}, "release_digest": "r" * 64, "artifact_digest": "a" * 64, "gate_mode": "local (advisory)", "state": "done",
            "statuses": {"s": "passed"}, "done_when": "s is ready", "first_failure": None, "other_failures": [], "not_yours": [], "coverage": None,
            "editable": {"dirs": ["service"], "manifest": "app.manifest.yaml", "manifest_keys": []}, "frozen": ["gate/"],
            "rerun": {"full": "x", "focused": None, "impact": "y"}, "evidence": {"claims": "a", "records": "b"}}
    D2 = PT.distill(done, {}, P, root); jsonschema.validate(D2, SCHEMA); assert D2["first_failure"] is None and D2["disclosure"] == "redacted"
