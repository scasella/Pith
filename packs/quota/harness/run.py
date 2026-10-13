"""harness/run.py — how this pack runs the candidate's library. FROZEN.

The library is never imported by the judge. A frozen driver (harness/driver.py or harness/driver.mjs, by
app.manifest.yaml:runtime) is started as a separate process under the candidate's identity and limits
(gate/sandbox.py:run_as_candidate_full) with the program on its command line, and its one line of JSON is the
observation. There is no service, so gate/service.py (Supervised) is not used: nothing listens on a port and
nothing persists between runs except what a program carries itself (dump/load).
"""
import json, pathlib, sys
import yaml
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gate import sandbox as SB

DRIVER = {"python": [sys.executable, "-I", "harness/driver.py"], "node": ["node", "harness/driver.mjs"]}
LIMITS = {"python": {}, "node": {"RLIMIT_AS": None}}     # V8 reserves address space for WebAssembly (gate/sandbox.py limits)


def runtime(root=ROOT):
    p = pathlib.Path(root) / "app.manifest.yaml"
    return ((yaml.safe_load(p.read_text()) or {}) if p.exists() else {}).get("runtime") or "python"


class DriverFailed(AssertionError):
    pass


def run(steps, root=ROOT, timeout=60):
    """Run one program; returns the driver's results, one per step. A crash, a timeout or output that is not the
    driver's one JSON line is a failure of the candidate (the library broke the process it runs in)."""
    rt = runtime(root)
    code, out, err = SB.run_as_candidate_full(DRIVER[rt] + [json.dumps({"steps": steps})], cwd=root, timeout=timeout, limits=LIMITS[rt])
    lines = [l for l in (out or "").splitlines() if l.startswith('{"results"')]
    if code != 0 or len(lines) != 1:
        raise DriverFailed(f"driver exited {code}; stdout {out[-400:]!r}; stderr {err[-800:]!r}")
    res = json.loads(lines[0])["results"]
    if len(res) != len(steps): raise DriverFailed(f"{len(res)} results for {len(steps)} steps")
    return res
