// limiter.mjs — a sliding-window quota limiter that keeps, per key, one tally per instant at which something was
// granted, plus a running total, and drops tallies as they leave the window.
//
//   import { Limiter } from "./lib/limiter.mjs";
//   const lim = new Limiter({ limit: 3, window: 60, limits: { vip: 10 } });   // "vip" has 10, every other key 3
//   lim.acquire("alice", { now: 10 });   // { granted: true, remaining: 2, retryAfter: null }
//   lim.limitFor("vip");                 // 10
//
// Arithmetic is kept inside the safe-integer range: an instant near 2^53 plus a window would not be, so expiry is
// tested as `now - t >= window`, never `t + window <= now`.
import { Tally } from "./tally.mjs";

const MAX31 = 2 ** 31 - 1, MAX53 = Number.MAX_SAFE_INTEGER;
const KEY = /^[A-Za-z0-9_.:-]{1,64}$/;
const FORMAT = "tally/2";            // version 1 dumps ("tally/1") are converted by lib/migrate.mjs

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

function ownLimits(v) {
  if (typeof v !== "object" || v === null || Array.isArray(v) || ![Object.prototype, null].includes(Object.getPrototypeOf(v))) {
    throw new InvalidArgument("limits", "must be a plain object from keys to whole numbers");
  }
  const out = new Map();
  for (const [k, n] of Object.entries(v)) {
    if (!KEY.test(k) || typeof n !== "number" || !Number.isSafeInteger(n) || n < 1 || n > MAX31) {
      throw new InvalidArgument("limits", `${JSON.stringify(k)} must map to a whole number from 1 to ${MAX31}`);
    }
    out.set(k, n);
  }
  return out;
}

export class Limiter {
  #limit; #window; #own; #clock = 0; #tallies = new Map();

  constructor({ limit, window, limits = {} } = {}) {
    this.#limit = whole("limit", limit, 1, MAX31);
    this.#window = whole("window", window, 1, MAX31);
    this.#own = ownLimits(limits);
  }

  get limit() { return this.#limit; }
  get window() { return this.#window; }

  // the limit key k is held to: its own if the limiter was given one, the default otherwise
  limitFor(k) { key(k); return this.#own.get(k) ?? this.#limit; }

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
    const limit = this.#own.get(k) ?? this.#limit;
    const t = this.#tally(k, now);
    const used = t ? t.total : 0;
    if (used + cost <= limit) {
      (t ?? this.#tallies.set(k, new Tally()).get(k)).add(now, cost);
      return Object.freeze({ granted: true, remaining: limit - used - cost, retryAfter: null });
    }
    const retryAfter = cost > limit ? null : t.waitFor(used + cost - limit, now, this.#window);
    return Object.freeze({ granted: false, remaining: limit - used, retryAfter });
  }

  peek(k, { now } = {}) {
    key(k); whole("now", now, 0, MAX53);
    this.#tick(now);
    const t = this.#tally(k, now);
    return (this.#own.get(k) ?? this.#limit) - (t ? t.total : 0);
  }

  // tally/2|limit;window;clock|key:n,key:n (the keys with a limit of their own, possibly none) then one
  // |key=t:c,t:c,... per key with tallies that can still count
  dump() {
    const own = [...this.#own.keys()].sort().map((k) => `${k}:${this.#own.get(k)}`).join(",");
    const parts = [FORMAT, `${this.#limit};${this.#window};${this.#clock}`, own];
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
    if (parts[0] !== FORMAT || parts.length < 3) throw bad();
    const nums = parts[1].split(";");
    const num = (s) => (/^(0|[1-9][0-9]*)$/.test(s) ? Number(s) : NaN);
    if (nums.length !== 3) throw bad();
    const own = Object.create(null);
    for (const e of parts[2] === "" ? [] : parts[2].split(",")) {
      const i = e.lastIndexOf(":");
      if (i < 0 || e.slice(0, i) in own) throw bad();
      own[e.slice(0, i)] = num(e.slice(i + 1));
    }
    let lim;
    try { lim = new Limiter({ limit: num(nums[0]), window: num(nums[1]), limits: own }); whole("clock", num(nums[2]), 0, MAX53); }
    catch { throw bad(); }
    lim.#clock = num(nums[2]);
    const seen = new Set();
    for (const p of parts.slice(3)) {
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
      if (t.total > lim.limitFor(k)) throw bad();
      lim.#tallies.set(k, t);
    }
    return lim;
  }
}
