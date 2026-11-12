"""Registry of research methods (one agent each). To add one: copy _template.py, then list the
module in _MODULES below. See base.py for the life cycle draft -> paper -> (live, separate step)."""
from __future__ import annotations

from services.api.methods import (
    breakout_confirm,
    bull_flag,
    breakout_retest,
    false_breakout,
    momentum_breakout,
    mtf_trend,
    trend_reentry,
    volatility_expansion,
)
from services.api.methods.base import Method

_MODULES = (
    trend_reentry,
    mtf_trend,
    breakout_confirm,
    breakout_retest,
    momentum_breakout,
    volatility_expansion,
    false_breakout,
    bull_flag,
)
METHODS: tuple[Method, ...] = tuple(module.METHOD for module in _MODULES)
BY_ID: dict[str, Method] = {method.id: method for method in METHODS}
BY_AGENT: dict[str, Method] = {method.agent_id: method for method in METHODS}
# Methods of the user's list that already had an agent before this registry existed.
EXISTING = {
    "Pullback": "Larry Connors (Hồi giá M15) — agent tiền thật",
    "Reversal": "Richard Wyckoff (Đảo chiều M15) — phòng nghiên cứu",
}
# Walk-forward on saved M15 history, $10k, spread 0.2 (2026-11-09): select 2022-24 / test 2025-26.
# "flag" is measured on M30 (its own frame) through the same backtest engine.
# A method qualifies for real money only if both periods are positive (and then only with the user's OK).
TESTED = {
 # bull flag through the backtest engine on its own frames (2026-11-10)
 "flag": {"2022-24": {"trades": 39, "averageR": 0.335, "profitFactor": 1.75, "totalR": 13.1},
          "2025-26": {"trades": 37, "averageR": 0.288, "profitFactor": 1.6, "totalR": 10.7}},
 "flag-H1": {"2022-24": {"trades": 35, "averageR": 0.099, "profitFactor": 1.19, "totalR": 3.4},
             "2025-26": {"trades": 48, "averageR": 0.081, "profitFactor": 1.16, "totalR": 3.9}},
 "reentry": {
  "2022-24": {
   "trades": 581,
   "averageR": 0.006,
   "profitFactor": 1.01,
   "totalR": 3.4
  },
  "2025-26": {
   "trades": 486,
   "averageR": 0.094,
   "profitFactor": 1.17,
   "totalR": 45.6
  }
 },
 "mtf": {
  "2022-24": {
   "trades": 480,
   "averageR": -0.087,
   "profitFactor": 0.86,
   "totalR": -41.8
  },
  "2025-26": {
   "trades": 344,
   "averageR": -0.044,
   "profitFactor": 0.93,
   "totalR": -15.2
  }
 },
 "brkconfirm": {
  "2022-24": {
   "trades": 1126,
   "averageR": -0.029,
   "profitFactor": 0.95,
   "totalR": -33.2
  },
  "2025-26": {
   "trades": 770,
   "averageR": 0.091,
   "profitFactor": 1.15,
   "totalR": 70.4
  }
 },
 "retest": {
  "2022-24": {
   "trades": 748,
   "averageR": -0.035,
   "profitFactor": 0.95,
   "totalR": -26.1
  },
  "2025-26": {
   "trades": 559,
   "averageR": 0.012,
   "profitFactor": 1.02,
   "totalR": 6.9
  }
 },
 "momentum": {
  "2022-24": {
   "trades": 896,
   "averageR": -0.093,
   "profitFactor": 0.84,
   "totalR": -83.6
  },
  "2025-26": {
   "trades": 646,
   "averageR": 0.021,
   "profitFactor": 1.04,
   "totalR": 13.7
  }
 },
 "volexp": {
  "2022-24": {
   "trades": 246,
   "averageR": -0.164,
   "profitFactor": 0.77,
   "totalR": -40.3
  },
  "2025-26": {
   "trades": 175,
   "averageR": -0.075,
   "profitFactor": 0.89,
   "totalR": -13.1
  }
 },
 "fakeout": {
  "2022-24": {
   "trades": 1331,
   "averageR": -0.086,
   "profitFactor": 0.86,
   "totalR": -114.3
  },
  "2025-26": {
   "trades": 977,
   "averageR": -0.036,
   "profitFactor": 0.94,
   "totalR": -35.6
  }
 }
}


def verdict(method_id: str) -> str:
    found = TESTED.get(method_id)
    if not found:
        return "Chưa kiểm thử"
    good = [(row["averageR"] or 0) >= MIN_AVERAGE_R and (row["profitFactor"] or 0) >= MIN_PROFIT_FACTOR for row in (found["2022-24"], found["2025-26"])]
    if all(good):
        return "Đạt cả hai giai đoạn"
    if any(good):
        return "Chỉ đạt một giai đoạn"
    return "Không có lợi thế"


# The bar a method must clear in BOTH periods (the live trend agent does ~+0.15R, PF ~1.3).
MIN_AVERAGE_R = 0.05
MIN_PROFIT_FACTOR = 1.10

assert len(BY_ID) == len(METHODS), "method ids must be unique"


def paper_ids() -> tuple[str, ...]:
    """Strategy keys whose signals are recorded as paper trades."""
    return tuple(method.id for method in METHODS if method.status == "paper")


def evaluate_all(market: dict[str, object]) -> list[dict[str, object]]:
    return [method.evaluate(market) for method in METHODS]
