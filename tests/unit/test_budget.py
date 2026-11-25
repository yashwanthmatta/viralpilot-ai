import pytest
from vp_shared import budget
from vp_shared.models import ContentItem


def test_reserve_within_limit(s):
    e = budget.reserve(s, category="llm", estimate_usd=0.40)
    assert budget.summary(s).today == pytest.approx(0.40)
    budget.commit(s, e, 0.10)
    assert budget.summary(s).today == pytest.approx(0.10)


def test_daily_limit_counts_outstanding_reservations(s):
    budget.reserve(s, category="llm", estimate_usd=0.60)
    with pytest.raises(budget.BudgetExceeded) as ei:
        budget.reserve(s, category="render", estimate_usd=0.50)
    assert ei.value.scope == "daily"


def test_released_reservation_frees_budget(s):
    e = budget.reserve(s, category="llm", estimate_usd=0.90)
    budget.release(s, e)
    budget.reserve(s, category="llm", estimate_usd=0.90)


def test_failed_block_is_still_charged(s):
    with pytest.raises(RuntimeError):
        with budget.spend(s, category="llm", estimate_usd=0.30):
            raise RuntimeError("api error after billing")
    assert budget.summary(s).today == pytest.approx(0.30)


def test_per_item_limit(s):
    item = ContentItem(fingerprint="x")
    s.add(item)
    s.flush()
    budget.reserve(s, category="llm", estimate_usd=0.45, item_id=item.id)
    with pytest.raises(budget.BudgetExceeded) as ei:
        budget.reserve(s, category="llm", estimate_usd=0.10, item_id=item.id)
    assert ei.value.scope == "per-video"


def test_negative_estimate_rejected(s):
    with pytest.raises(ValueError):
        budget.reserve(s, category="llm", estimate_usd=-1)
