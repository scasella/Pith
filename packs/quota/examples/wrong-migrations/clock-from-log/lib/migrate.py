"""lib/migrate.py --state DIR: convert stored version 1 dumps ("sliding-log/1") to this version's format in place.

harness/LIBRARY.md, "Upgrading from version 1". Each `<name>.dump` in DIR is read; a version 1 dump becomes a dump with
the same limit, window, clock and grants and no per-key limits; a version 2 dump is left as it is (so a second run
changes nothing). Anything else in DIR refuses the whole run before a single file is written.
"""
import argparse, json, os, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from limiter import Limiter, LimiterError   # noqa: E402

V1_FIELDS = {"format", "limit", "window", "clock", "log"}


def convert(text):
    """The version 2 text for one stored dump, or None when it already is one. ValueError when it is neither."""
    try:
        Limiter.load(text)
        return None                                            # already this version's: nothing to do
    except LimiterError:
        pass
    d = json.loads(text)                                       # JSONDecodeError is a ValueError
    if not isinstance(d, dict) or set(d) != V1_FIELDS or d["format"] != "sliding-log/1":
        raise ValueError("neither a version 1 nor a version 2 dump")
    v2 = dict(d, format="sliding-log/2", limits={})           # same limit, window, clock and grants; no key has its own limit
    grants = [t for entries in d["log"].values() for t, _ in entries]
    v2["clock"] = max(grants, default=0)                       # DEFECT: "the clock is just a cache of the newest grant": rebuilt from the log, it forgets peeks and denials made later
    try:
        return Limiter.load(json.dumps(v2)).dump()             # load checks what version 1's load checked
    except LimiterError as e:
        raise ValueError(f"a version 1 dump that does not load: {e}") from e


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--state", required=True); a = ap.parse_args()
    state = pathlib.Path(a.state)
    if not state.is_dir(): sys.exit(f"refused: {state} is not a directory")
    out, problems, leftovers = {}, [], []
    for p in sorted(state.iterdir()):
        if p.is_file() and p.name.startswith(".") and p.name.endswith(".dump.migrating"):
            leftovers.append(p); continue                      # an interrupted run's temporary copy: its dump is intact
        if not p.is_file() or p.suffix != ".dump":
            problems.append(f"{p.name}: not a stored dump (<name>.dump)"); continue
        try:
            new = convert(p.read_text())
        except (ValueError, UnicodeDecodeError) as e:
            problems.append(f"{p.name}: {e}"); continue
        if new is not None: out[p] = new
    if problems: sys.exit("refused, nothing written:\n  " + "\n  ".join(problems))
    for p in leftovers: p.unlink()
    for p, new in out.items():                                 # each file replaced whole: a crash leaves it old or new
        tmp = p.with_name(f".{p.name}.migrating")
        tmp.write_text(new); os.replace(tmp, p)
    print(f"converted {len(out)} version 1 dump(s); {len(list(state.glob('*.dump'))) - len(out)} already version 2")


if __name__ == "__main__":
    main()
