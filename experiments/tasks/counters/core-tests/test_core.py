import pytest
from core import decide


def test_accepts_below_the_bound(): assert decide(0, 3) == ("OK", 1) and decide(2, 3) == ("OK", 3)
def test_refuses_at_the_bound(): assert decide(3, 3) == ("REFUSED", 3)
def test_rejects_impossible_state():
    with pytest.raises(ValueError): decide(4, 3)
