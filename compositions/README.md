# compositions/

Composition contracts (format `pith.composition/v1`, `docs/rfc/0004-safe-evolution.md` § 3): the components of a
workflow, the state each owns, the effects through which it may change, each component's local invariants, the
invariants that span components, the transitions that must be atomic, and the assumptions between them. The model is
TLA+ in its native form.

```bash
python3 gate/cli.py compose check compositions/ledger-receipts
```

- `ledger-receipts/` — a ledger (owns the applied effects, up to a capacity) and a receipt store (owns the outcome each
  client is told). Separate state; one shared invariant, `ReceiptAgrees`. `wrong/receipt-first` records the receipt
  before applying the effect: each component keeps its own rules, and the joint invariant fails.
- `reservation-kernels/` — the reservation pack's two kernels (v0.12.0): authorization (owns the statuses and the
  holds) and posting (owns the posted total and what each capture posted). Two shared invariants: `INV1` (posted plus
  reserved never exceeds the limit) and `CaptureAgrees` (a request is posted in one kernel exactly when the other
  posted its amount); `Decide` and `Capture` must be atomic across both. Three known-wrong integrations
  (`ignores-posting`, `capture-forgets-posting`, `split-capture`) keep each kernel's rules and break exactly the
  invariants they name. `correspondence/` shows with TLC, in both directions, that the integration has the same
  behaviours as the pack's frozen design obligations (`obligations/design/CoreActions.tla`), so this contract is a
  restatement of what the pack already required, not a second definition (`validation/compositions.py`).
- `booking-quota/` — a runtime composition (v0.13.0, `docs/rfc/0007-autonomous-assurance-and-runtime-composition.md` § 3): a booking
  component (a `pith.booking` service), a quota component (a `pith.quota` library behind an idempotent wrapper) and a coordinator that
  owns the saga log and the receipts. Shared invariants `QuotaMatchesBookings` and `ReceiptAgrees`. `gate/compose.py check` model-checks
  it; `compose verify` runs the three processes behind judge-owned fault proxies, kills the coordinator between the steps of a
  reservation, drops answers and severs the compensating cancel, and reads the invariants from the components' own state;
  `compose stagger` upgrades the booking component from v1 to v2 while the other two keep their state. `split-saga-leak` and
  `orphan-receipt-on-abort` (model twins and runtime candidates), `touches-quota-store` and `drops-compensated` (staggered migrations)
  must each be refused for exactly their defect (`validation/compositions.py`).

The check is bounded model checking of the model, and holds only under the stated atomicity assumptions; whether an
implementation's transactions match the modelled steps is a separate obligation the check does not discharge.
