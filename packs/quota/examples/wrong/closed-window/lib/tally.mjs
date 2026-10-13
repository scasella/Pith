// tally.mjs — the grants of one key: [instant, cost] pairs in increasing instant order (grants at one instant are
// merged), a start index instead of shifting the array, and a running total.
export class Tally {
  #at = []; #cost = []; #start = 0; total = 0;

  add(at, cost) {
    const n = this.#at.length;
    if (n > this.#start && this.#at[n - 1] === at) this.#cost[n - 1] += cost;
    else { this.#at.push(at); this.#cost.push(cost); }
    this.total += cost;
  }

  // drop what no longer counts at `now`: a grant at t counts while now - t < window
  expire(now, window) {
    while (this.#start < this.#at.length && now - this.#at[this.#start] > window) {   // DEFECT: a grant still counts at t + window (closed window [now - window, now])
      this.total -= this.#cost[this.#start]; this.#start++;
    }
    if (this.#start > 64 && this.#start * 2 > this.#at.length) {
      this.#at = this.#at.slice(this.#start); this.#cost = this.#cost.slice(this.#start); this.#start = 0;
    }
  }

  // the least r >= 1 at which at least `need` has expired, oldest first
  waitFor(need, now, window) {
    for (let i = this.#start; i < this.#at.length; i++) {
      need -= this.#cost[i];
      if (need <= 0) return window - (now - this.#at[i]);
    }
    throw new Error("unreachable: everything expires within one window");
  }

  entries() {
    const out = [];
    for (let i = this.#start; i < this.#at.length; i++) out.push([this.#at[i], this.#cost[i]]);
    return out;
  }
}
