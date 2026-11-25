"""Expected-profit model for choosing campaigns. Every output is an ESTIMATE.

Views per clip are modelled as log-normal: a few clips get most views, which
is what short-form data looks like. The expected payout is computed over 40
evenly spaced quantiles of that distribution, so the CPM minimum-payout
threshold and the per-video cap are handled exactly rather than averaged away.

Priors (used only until we have our own data) are deliberately conservative
and the evaluation says which inputs came from priors.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from statistics import NormalDist, median

PRIOR_MEDIAN_VIEWS = 300.0
PRIOR_SIGMA = 1.6           # spread of log(views); ~1.6 => top 5% of clips get ~14x the median
PRIOR_P_APPROVAL = 0.5
PRIOR_P_PAYMENT = 0.8
DEFAULT_COST_PER_CLIP = 0.15  # local render + small model calls; replaced by measured cost
QUALIFIED_SHARE = 0.85        # share of raw views campaigns typically count as qualified
_N = 40


@dataclass
class ViewModel:
    median: float
    sigma: float
    source: str  # "prior" or "history(n=…)"

    def quantiles(self) -> list[float]:
        nd = NormalDist(math.log(max(self.median, 1.0)), self.sigma)
        return [math.exp(nd.inv_cdf((i + 0.5) / _N)) for i in range(_N)]


def view_model(history_views: list[int]) -> ViewModel:
    xs = [v for v in history_views if v is not None and v >= 0]
    if len(xs) < 5:
        return ViewModel(PRIOR_MEDIAN_VIEWS, PRIOR_SIGMA, "prior")
    logs = [math.log(v + 1) for v in xs]
    mu = sum(logs) / len(logs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in logs) / (len(logs) - 1)) or 0.5
    return ViewModel(max(median(xs), 1.0), min(max(sd, 0.3), 3.0), f"history(n={len(xs)})")


@dataclass
class Evaluation:
    expected_payout: float          # before approval/payment risk and fees
    risk_adjusted_revenue: float
    production_cost: float
    expected_profit: float
    p_reach_min: float              # chance a clip reaches the campaign's minimum payout
    p_approval: float
    p_payment: float
    fee_pct: float
    clips_affordable: int | None    # how many clips the remaining budget can pay at the expected payout
    view_model: str
    assumptions: list[str] = field(default_factory=list)
    label: str = "estimate"

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(
    *,
    payout_model: str,
    rate_per_1k: float | None,
    flat_reward: float | None,
    min_payout: float | None,
    max_payout_per_video: float | None,
    budget_remaining: float | None,
    fee_pct: float,
    views: ViewModel,
    p_approval: float | None = None,
    p_payment: float | None = None,
    cost_per_clip: float | None = None,
) -> Evaluation:
    assumptions: list[str] = []
    if views.source == "prior":
        assumptions.append(f"views: conservative prior, median {PRIOR_MEDIAN_VIEWS:.0f}")
    pa = p_approval if p_approval is not None else PRIOR_P_APPROVAL
    pp = p_payment if p_payment is not None else PRIOR_P_PAYMENT
    if p_approval is None:
        assumptions.append(f"approval rate: prior {PRIOR_P_APPROVAL}")
    if p_payment is None:
        assumptions.append(f"payment reliability: prior {PRIOR_P_PAYMENT}")
    cost = cost_per_clip if cost_per_clip is not None else DEFAULT_COST_PER_CLIP
    if cost_per_clip is None:
        assumptions.append(f"production cost: default ${DEFAULT_COST_PER_CLIP}")

    if payout_model == "flat":
        payout, p_min = float(flat_reward or 0.0), 1.0
    else:
        rate = float(rate_per_1k or 0.0)
        cap = max_payout_per_video if max_payout_per_video else math.inf
        floor = float(min_payout or 0.0)
        pays = []
        for v in views.quantiles():
            amount = min(rate * v * QUALIFIED_SHARE / 1000.0, cap)
            pays.append(amount if amount >= floor else 0.0)
        payout = sum(pays) / len(pays)
        p_min = sum(1 for p in pays if p > 0) / len(pays)
    fee = min(max(fee_pct, 0.0), 1.0)
    risk_adj = payout * pa * pp * (1 - fee)
    affordable = None
    if budget_remaining is not None and payout > 0:
        affordable = int(budget_remaining // payout)
    return Evaluation(
        expected_payout=round(payout, 4),
        risk_adjusted_revenue=round(risk_adj, 4),
        production_cost=round(cost, 4),
        expected_profit=round(risk_adj - cost, 4),
        p_reach_min=round(p_min, 3),
        p_approval=pa,
        p_payment=pp,
        fee_pct=fee,
        clips_affordable=affordable,
        view_model=views.source,
        assumptions=assumptions,
    )
