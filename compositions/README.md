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

The check is bounded model checking of the model, and holds only under the stated atomicity assumptions; whether an
implementation's transactions match the modelled steps is a separate obligation the check does not discharge.
