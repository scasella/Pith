// limiter.mjs — a sliding-window quota limiter that keeps, per key, one tally per instant at which something was
// granted, plus a running total, and drops tallies as they leave the window.
//
//   import { Limiter } from "./lib/limiter.mjs";
//   const lim = new Limiter({ limit: 3, window: 60 });
//   lim.acquire("alice", { now: 10 });   // { granted: true, remaining: 2, retryAfter: null }
//
// Arithmetic is kept inside the safe-integer range: an instant near 2^53 plus a window would not be, so expiry is
// tested as `now - t >= window`, never `t + window <= now`.
import { Tally } from "./tally.mjs";

const MAX31 = 2 ** 31 - 1, MAX53 = Number.MAX_SAFE_INTEGER;
const KEY = /^[A-Za-z0-9_.:-]{1,64}$/;
const FORMAT = "tally/1";

export class LimiterError extends Error {
  constructor(message) { super(message); this.name = new.target.name; }
}
export class InvalidArgument extends LimiterError {
  constructor(argument, detail) { super(`${argument} ${detail}`); this.argument = argument; }
}
export class ClockRegression extends LimiterError {
  constructor(now, clock) { super(`now=${now} is before the limiter's clock (${clock})`); this.now = now; this.clock = clock; }
}

function whole(name, v, lo, hi) {
  if (typeof v !== "number" || !Number.isSafeInteger(v) || v < lo || v > hi) {
    throw new InvalidArgument(name, `must be a whole number from ${lo} to ${hi} (got ${JSON.stringify(v) ?? String(v)})`);
  }
  return v;
}
function key(k) {
  if (typeof k !== "string" || !KEY.test(k)) throw new InvalidArgument("key", "must be 1-64 characters of A-Z a-z 0-9 _ . : -");
  return k;
}

export class Limiter {
  #limit; #window; #clock = 0; #tallies = new Map();

  constructor({ limit, window } = {}) {
    this.#limit = whole("limit", limit, 1, MAX31);
    this.#window = whole("window", window, 1, MAX31);
  }

  get limit() { return this.#limit; }
  get window() { return this.#window; }

  #tick(now) {
    if (now < this.#clock) throw new ClockRegression(now, this.#clock);
    this.#clock = now;
  }

  #tally(k, now) {
    const t = this.#tallies.get(k);
    if (!t) return null;
    t.expire(now, this.#window);
    if (t.total === 0) { this.#tallies.delete(k); return null; }
    return t;
  }

  acquire(k, { now, cost = 1 } = {}) {
    key(k); whole("cost", cost, 1, MAX31); whole("now", now, 0, MAX53);
    this.#tick(now);
    const t = this.#tally(k, now);
    const used = t ? t.total : 0;
    if (used + cost <= this.#limit) {
      (t ?? this.#tallies.set(k, new Tally()).get(k)).add(now, cost);
      return Object.freeze({ granted: true, remaining: this.#limit - used - cost, retryAfter: null });
    }
    const retryAfter = cost > this.#limit ? null : t.waitFor(used + cost - this.#limit, now, this.#window);
    return Object.freeze({ granted: false, remaining: this.#limit - used, retryAfter });
  }

  peek(k, { now } = {}) {
    key(k); whole("now", now, 0, MAX53);
    this.#tick(now);
    const t = this.#tally(k, now);
    return this.#limit - (t ? t.total : 0);
  }

  // limit;window;clock then one |key=t:c,t:c,... per key with tallies that can still count
  dump() {
    const parts = [FORMAT, `${this.#limit};${this.#window};${this.#clock}`];
    for (const k of [...this.#tallies.keys()].sort()) {
      const t = this.#tally(k, this.#clock);
      if (t) parts.push(`${k}=${t.entries().map(([at, c]) => `${at}:${c}`).join(",")}`);
    }
    return parts.join("|");
  }

  static load(text) {
    const bad = () => new InvalidArgument("text", "is not something Limiter.dump() produced");
    if (typeof text !== "string") throw bad();
    const parts = text.split("|");
    if (parts[0] !== FORMAT || parts.length < 2) throw bad();
    const nums = parts[1].split(";");
    const num = (s) => (/^(0|[1-9][0-9]*)$/.test(s) ? Number(s) : NaN);
    if (nums.length !== 3) throw bad();
    let lim;
    try { lim = new Limiter({ limit: num(nums[0]), window: num(nums[1]) }); whole("clock", num(nums[2]), 0, MAX53); }
    catch { throw bad(); }
    lim.#clock = num(nums[2]);
    const seen = new Set();
    for (const p of parts.slice(2)) {
      const eq = p.indexOf("=");
      const k = p.slice(0, eq);
      if (eq < 0 || !KEY.test(k) || seen.has(k)) throw bad();
      seen.add(k);
      const t = new Tally();
      let prev = -1;
      for (const e of p.slice(eq + 1).split(",")) {
        const [a, c, ...rest] = e.split(":").map(num);
        if (rest.length || !Number.isSafeInteger(a) || !Number.isSafeInteger(c) || c < 1 || a <= prev || a > lim.#clock || lim.#clock - a >= lim.#window) throw bad();
        t.add(a, c); prev = a;
      }
      if (t.total > lim.#limit) throw bad();
      lim.#tallies.set(k, t);
    }
    return lim;
  }
}
