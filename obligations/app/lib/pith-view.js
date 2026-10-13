/*
 * obligations/app/lib/pith-view.js — optional client-state module for Pith application UIs. FROZEN.
 *
 * Five pieces of state, kept apart because the Club Desk / Office Desk review found defects exactly where UIs merged
 * them: the DRAFT selection (what is typed), the LOADED view (what a successful response produced, and whether it is
 * still current), the LOADING request (which may be superseded), the PENDING operation, and the RECEIPT (what the
 * service said about an operation, bound to that operation's own account and request).
 *
 * The transitions are pure functions (state, ...) -> state; the driver (PithView.create) wires them to fetch. Rules
 * they implement (UI-CONTRACT.md § Interaction obligations):
 *   I1/I2  an action on a row targets the row's own account; a row's account comes from the response that drew it
 *   I3     a load response is applied only if it answers the newest load (sequence numbers), never a superseded one
 *   I4     a refresh failure marks the loaded view stale; it never touches the receipt
 *   I5     outcome classes: 2xx → the service's answer; 4xx → REJECTED (nothing happened); 5xx/network → UNKNOWN
 *   I6     a receipt carries its account and request; switching accounts keeps it scoped, never re-labels it
 *
 * No framework, no DOM. Works as a browser <script> (window.PithView) and as a CommonJS module (tests).
 * Tests: node --test obligations/app/lib/test_pith_view.mjs
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PithView = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const initial = () => Object.freeze({ draft: null, loading: null, loaded: null, pending: null, receipt: null, seq: 0, problem: null });

  /** Outcome class of an HTTP exchange. status is null when no response arrived. */
  function classify(status) {
    if (status === null || status === undefined) return "UNKNOWN";
    if (status >= 200 && status < 300) return "OK";
    if (status >= 400 && status < 500) return "REJECTED";
    return "UNKNOWN";
  }

  const T = {
    draft(s, account) { return { ...s, draft: account }; },

    loadStarted(s, account) {
      const seq = s.seq + 1;
      return { ...s, seq, loading: { account, seq } };
    },

    loadSucceeded(s, seq, data) {
      if (!s.loading || s.loading.seq !== seq) return s;                       // superseded: ignore (I3)
      return { ...s, loading: null, problem: null, loaded: { account: data.id, data, state: "current" } };
    },

    loadFailed(s, seq, message) {
      if (!s.loading || s.loading.seq !== seq) return s;                       // superseded failure: ignore
      const target = s.loading.account;
      const loaded = s.loaded && s.loaded.account === target ? { ...s.loaded, state: "stale" } : s.loaded;   // I2, I4
      return { ...s, loading: null, loaded, problem: { account: target, message } };
    },

    opStarted(s, op, account, request) {
      const seq = s.seq + 1;
      return { ...s, seq, pending: { op, account, request, seq } };
    },

    opSettled(s, seq, status, body) {
      if (!s.pending || s.pending.seq !== seq) return s;
      const p = s.pending, cls = classify(status);
      const receipt = { op: p.op, account: p.account, request: p.request, outcome: cls, body: body || null,
                        decision: cls === "OK" && p.op === "authorize" && body ? body.decision : cls === "OK" ? "DONE" : cls };
      return { ...s, pending: null, receipt };
    },
  };

  /** Rows of the loaded view, each bound to the loaded account (I1). */
  function rows(s) {
    if (!s.loaded) return [];
    return Object.entries(s.loaded.data.holds || {}).map(([request, amount]) => ({ account: s.loaded.account, request: Number(request), amount }));
  }

  /** The driver: owns a state value, runs fetches, applies transitions, calls onChange(state) after each one. */
  function create({ fetch: f = (typeof fetch !== "undefined" ? fetch.bind(globalThis) : null), onChange = () => {} } = {}) {
    let state = initial();
    const set = (next) => { if (next !== state) { state = next; onChange(state); } return state; };

    async function exchange(method, path, body) {
      try {
        const r = await f(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
        let data = null; try { data = await r.json(); } catch (_) { data = null; }
        return { status: r.status, data };
      } catch (_) { return { status: null, data: null }; }
    }

    async function load(account) {
      set(T.draft(state, account));
      set(T.loadStarted(state, account)); const seq = state.seq;
      const r = await exchange("GET", `/accounts/${account}`);
      return set(classify(r.status) === "OK" ? T.loadSucceeded(state, seq, r.data)
                                              : T.loadFailed(state, seq, (r.data && r.data.error) || (r.status ? `HTTP ${r.status}` : "no response")));
    }

    async function operate(op, account, request, body) {
      set(T.opStarted(state, op, account, request)); const seq = state.seq;
      const r = await exchange("POST", `/accounts/${account}/${op}`, body);
      set(T.opSettled(state, seq, r.status, r.data));
      if (state.loaded && state.loaded.account === account) await load(account);   // refresh; its failure only marks the view stale
      return state;
    }

    return {
      get state() { return state; },
      draft: (account) => set(T.draft(state, account)),
      load,
      async create(account, limit) {
        const r = await exchange("POST", "/accounts", { id: account, limit });
        if (classify(r.status) === "OK") await load(account);
        return { status: r.status, data: r.data };
      },
      /** Authorize against the LOADED account (never the draft). Returns null when nothing is loaded. */
      authorize(request, amount) {
        if (!state.loaded) return Promise.resolve(null);
        return operate("authorize", state.loaded.account, request, { request_id: request, amount });
      },
      /** Release or capture a row returned by rows(): the row carries its own account (I1). */
      act(op, row) { return operate(op, row.account, row.request, { request_id: row.request }); },
      rows: () => rows(state),
      events: () => exchange("GET", "/events"),
    };
  }

  return { initial, classify, transitions: T, rows, create };
});
