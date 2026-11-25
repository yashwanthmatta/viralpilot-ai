"""Evidence-based scaling: decide tomorrow's video volume from real money.

Only confirmed revenue counts as evidence for growth. Pending amounts are
reported but never justify spending more. Output never exceeds the ceiling you
set, and never grows while any publishing account is unhealthy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

MIN_VIDEOS_FOR_DECISION = 20
MIN_PAID_FOR_GROWTH = 5
GROWTH_MARGIN = 1.2


@dataclass
class ScalingInput:
    current_per_day: int
    ceiling: int
    floor: int
    videos_14d: int
    paid_videos_14d: int
    confirmed_revenue_14d: float
    pending_revenue_14d: float
    cost_14d: float
    unhealthy_accounts: int


@dataclass
class ScalingDecision:
    new_per_day: int
    action: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def decide(x: ScalingInput) -> ScalingDecision:
    cur = max(min(x.current_per_day, x.ceiling), x.floor)
    if x.unhealthy_accounts:
        return ScalingDecision(max(cur - 1, x.floor), "reduce",
                               f"{x.unhealthy_accounts} account(s) unhealthy; protecting accounts first")
    if x.videos_14d < MIN_VIDEOS_FOR_DECISION:
        return ScalingDecision(cur, "hold", f"only {x.videos_14d} videos in 14 days; not enough evidence yet")
    if x.confirmed_revenue_14d + x.pending_revenue_14d <= 0 and x.cost_14d > 0:
        return ScalingDecision(max(cur - 1, x.floor), "reduce",
                               f"${x.cost_14d:.2f} spent on {x.videos_14d} videos with no revenue; cutting volume")
    if (x.paid_videos_14d >= MIN_PAID_FOR_GROWTH and x.confirmed_revenue_14d > x.cost_14d * GROWTH_MARGIN
            and cur < x.ceiling):
        return ScalingDecision(cur + 1, "grow",
                               f"confirmed ${x.confirmed_revenue_14d:.2f} vs cost ${x.cost_14d:.2f} over 14 days")
    return ScalingDecision(cur, "hold", "results don't yet justify more spend"
                           if cur < x.ceiling else f"at your ceiling of {x.ceiling}/day")
