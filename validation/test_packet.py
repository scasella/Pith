"""validation/test_packet.py — unit tests for gate/packet.py (failure categories, counterexamples, the packet) and the
manifest `include` rules in gate/workspace.py, on canned tool output. CI runs them; the end-to-end runs are
validation/packets.py and validation/judge_wrong.py.

    python3 -m pytest validation/test_packet.py -q
"""
import json, pathlib, sys
import jsonschema
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
