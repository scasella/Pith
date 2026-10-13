# core-tests condition: what the agent is given besides the task statement

- `core.py` — a trusted decision function with its conventional unit tests (`test_core.py`): `decide(tally, bound)`
  returns the outcome and the new tally. It is the "good infrastructure" of this condition: correct, tested, small.
- `test_service_skeleton.py` — conventional example-based tests of the HTTP contract against a running service, which
  the agent may extend. They are the condition's own acceptance; they are not the experiment's external criteria.

Nothing here knows about Pith's judge, packs or evidence. The condition separates the benefit of starting from good
infrastructure from the additional benefit of independent behavioural obligations and evidence.
