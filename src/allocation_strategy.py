"""Rule-based allocation model for the ETF competition.

The model is intentionally compact: it uses contest-horizon momentum, a 200-day
trend filter, realized volatility, and defensive stress sleeves. All weights are
long-only, sum to 100%, and can be constrained by the weekly 25 percentage point
total allocation-change rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf


ASSETS = ("ACWI", "AGG", "GLD", "BSV")
ACTIVE_ASSETS = ("ACWI", "AGG", "GLD")
DEFAULT_CAPS = pd.Series({"ACWI": 0.90, "AGG": 0.55, "GLD": 0.55, "BSV": 1.00})
INITIAL_BACKTEST_WEIGHTS = pd.Series(0.25, index=ASSETS)


@dataclass(frozen=True)
class AllocationDecision:
    """Container for one model decision."""

    signal_date: pd.Timestamp
    target_weights: pd.Series
    submitted_weights: pd.Series
    metrics: pd.DataFrame
    eligible_assets: tuple[str, ...]
    bsv_floor: float
    regime: str
    acwi_power_mode: bool
    gld_phoenix_sleeve: bool
    turnover_from_previous: float | None


def fetch_adjusted_close(
    tickers: Iterable[str] = ASSETS,
    start: str = "2008-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """Download adjusted close prices from Yahoo Finance."""

    tickers = tuple(tickers)
    data = yf.download(
        list(tickers),
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="column",
    )
    if data.empty:
        raise RuntimeError("No price data was downloaded from Yahoo Finance.")

    if isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns.get_level_values(0):
            close = data["Close"]
        else:
            close = data.xs("Close", axis=1, level=-1)
    else:
        close = data[["Close"]].rename(columns={"Close": tickers[0]})

    close = close.reindex(columns=tickers).dropna(how="any")
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.astype(float)


def as_weight_series(weights: pd.Series | dict[str, float] | Iterable[float]) -> pd.Series:
    """Return a decimal weight series indexed by the four project tickers."""

    if isinstance(weights, pd.Series):
        out = weights.reindex(ASSETS)
    elif isinstance(weights, dict):
        out = pd.Series(weights, index=ASSETS)
    else:
        out = pd.Series(list(weights), index=ASSETS)
    return out.astype(float)


def validate_weights(weights: pd.Series, tolerance: float = 1e-6) -> None:
    """Raise ValueError if weights violate project constraints."""

    weights = as_weight_series(weights)
    if weights.isna().any():
        raise ValueError("Weights must be provided for all four assets.")
    if (weights < -tolerance).any() or (weights > 1 + tolerance).any():
        raise ValueError("Every weight must be between 0% and 100%.")
    if abs(float(weights.sum()) - 1.0) > tolerance:
        raise ValueError(f"Weights must sum to 100%; got {weights.sum():.8f}.")


def limit_total_allocation_change(
    previous_weights: pd.Series,
    target_weights: pd.Series,
    limit: float = 0.25,
) -> pd.Series:
    """Scale a rebalance so sum(abs(new - previous)) is at most `limit`.

    The guidelines phrase this as a maximum of 25 percentage points in total
    allocation change, so the implementation uses L1 distance across assets.
    """

    previous = as_weight_series(previous_weights)
    target = as_weight_series(target_weights)
    validate_weights(previous)
    validate_weights(target)

    difference = target - previous
    total_change = float(difference.abs().sum())
    if total_change <= limit + 1e-12:
        return target

    limited = previous + difference * (limit / total_change)
    limited = limited.clip(lower=0, upper=1)
    limited = limited / limited.sum()
    validate_weights(limited)
    return limited


def compute_signal_metrics(
    prices: pd.DataFrame,
    as_of: str | pd.Timestamp | None = None,
    short_window: int = 63,
    medium_window: int = 126,
    trend_window: int = 200,
    volatility_window: int = 63,
    fast_window: int = 21,
) -> pd.DataFrame:
    """Compute model inputs on one signal date."""

    prices = prices.reindex(columns=ASSETS).dropna()
    if as_of is not None:
        prices = prices.loc[: pd.Timestamp(as_of)]
    min_length = max(short_window, medium_window, trend_window, volatility_window) + 1
    if len(prices) < min_length:
        raise ValueError(f"Need at least {min_length} daily observations for signals.")

    last = prices.iloc[-1]
    ret_fast = last / prices.iloc[-fast_window - 1] - 1
    ret_short = last / prices.iloc[-short_window - 1] - 1
    ret_medium = last / prices.iloc[-medium_window - 1] - 1
    momentum_score = 0.5 * ret_short + 0.5 * ret_medium
    sma_trend = prices.rolling(trend_window).mean().iloc[-1]
    trend_gap = last / sma_trend - 1
    volatility = prices.pct_change().tail(volatility_window).std() * np.sqrt(252)
    fast_volatility = prices.pct_change().tail(20).std() * np.sqrt(252)
    fast_drawdown = last / prices.tail(fast_window).cummax().max() - 1

    metrics = pd.DataFrame(
        {
            "last_price": last,
            "return_1m": ret_fast,
            "return_3m": ret_short,
            "return_6m": ret_medium,
            "momentum_score": momentum_score,
            "trend_gap_vs_200d": trend_gap,
            "drawdown_1m": fast_drawdown,
            "volatility_20d_ann": fast_volatility,
            "volatility_63d_ann": volatility,
        }
    )
    return metrics.reindex(ASSETS)


def _allocate_to_active_assets(
    raw_scores: pd.Series,
    active_budget: float,
    caps: pd.Series = DEFAULT_CAPS,
) -> pd.Series:
    """Allocate active budget by score while sending unused budget to BSV."""

    weights = pd.Series(0.0, index=ASSETS)
    raw_scores = raw_scores.dropna().clip(lower=0)
    raw_scores = raw_scores[raw_scores > 0]
    if raw_scores.empty or active_budget <= 0:
        weights["BSV"] = 1.0
        return weights

    caps = caps.reindex(ASSETS)
    active_weights = pd.Series(0.0, index=raw_scores.index)
    remaining_assets = list(raw_scores.index)
    remaining_budget = float(active_budget)

    for _ in range(len(remaining_assets) + 1):
        if not remaining_assets or remaining_budget <= 1e-12:
            break
        proportions = raw_scores[remaining_assets] / raw_scores[remaining_assets].sum()
        proposed = proportions * remaining_budget
        capped_assets = [
            asset
            for asset in remaining_assets
            if active_weights[asset] + proposed[asset] > caps[asset] + 1e-12
        ]
        if not capped_assets:
            active_weights[remaining_assets] += proposed
            remaining_budget = 0.0
            break
        for asset in capped_assets:
            add_amount = max(float(caps[asset] - active_weights[asset]), 0.0)
            active_weights[asset] += add_amount
            remaining_budget -= add_amount
            remaining_assets.remove(asset)

    weights[active_weights.index] = active_weights
    weights["BSV"] = 1.0 - float(weights[list(ACTIVE_ASSETS)].sum())
    weights = weights.clip(lower=0, upper=1)
    weights = weights / weights.sum()
    validate_weights(weights)
    return weights


def _comparison_vote(left: float, right: float, higher_is_better: bool = True) -> float:
    """Return a deterministic pairwise vote: 1 for left, 0 for right, 0.5 tie."""

    if abs(left - right) <= 1e-12:
        return 0.5
    if higher_is_better:
        return 1.0 if left > right else 0.0
    return 1.0 if left < right else 0.0


def compute_allocation_decision(
    prices: pd.DataFrame,
    as_of: str | pd.Timestamp | None = None,
    previous_weights: pd.Series | dict[str, float] | Iterable[float] | None = None,
    turnover_limit: float | None = 0.25,
) -> AllocationDecision:
    """Compute the model target and optional turnover-limited submitted weights."""

    prices = prices.reindex(columns=ASSETS).dropna()
    if as_of is not None:
        prices = prices.loc[: pd.Timestamp(as_of)]
    if prices.empty:
        raise ValueError("No prices available up to the requested signal date.")

    signal_date = pd.Timestamp(prices.index[-1])
    metrics = compute_signal_metrics(prices)

    acwi_stress = (
        metrics.loc["ACWI", "trend_gap_vs_200d"] < 0
        and metrics.loc["ACWI", "return_3m"] < 0
    )
    gld_stress = (
        metrics.loc["GLD", "trend_gap_vs_200d"] < 0
        and metrics.loc["GLD", "return_3m"] < 0
    )
    gld_supportive = (
        metrics.loc["GLD", "trend_gap_vs_200d"] > 0
        and metrics.loc["GLD", "return_6m"] > 0
    )

    if acwi_stress and gld_stress:
        regime = "dual growth stress"
        target_weights = pd.Series({"ACWI": 0.20, "AGG": 0.25, "GLD": 0.15, "BSV": 0.40})
        eligible = ("ACWI", "AGG", "GLD", "BSV")
    elif acwi_stress and gld_supportive:
        regime = "equity stress gold rotation"
        target_weights = pd.Series({"ACWI": 0.25, "AGG": 0.10, "GLD": 0.55, "BSV": 0.10})
        eligible = ("ACWI", "AGG", "GLD", "BSV")
    elif acwi_stress:
        regime = "equity stress defensive rotation"
        target_weights = pd.Series({"ACWI": 0.25, "AGG": 0.25, "GLD": 0.20, "BSV": 0.30})
        eligible = ("ACWI", "AGG", "GLD", "BSV")
    else:
        regime = "contest-horizon equity-gold vote"
        acwi_votes = sum(
            (
                _comparison_vote(
                    metrics.loc["ACWI", "return_3m"],
                    metrics.loc["GLD", "return_3m"],
                ),
                _comparison_vote(
                    metrics.loc["ACWI", "return_6m"],
                    metrics.loc["GLD", "return_6m"],
                ),
                _comparison_vote(
                    metrics.loc["ACWI", "trend_gap_vs_200d"],
                    metrics.loc["GLD", "trend_gap_vs_200d"],
                ),
                _comparison_vote(
                    metrics.loc["ACWI", "volatility_63d_ann"],
                    metrics.loc["GLD", "volatility_63d_ann"],
                    higher_is_better=False,
                ),
            )
        )
        # Normal regime is equity-first: four equal votes can move 40% of the
        # portfolio between ACWI and GLD, while stress rules handle defense.
        acwi_weight = 0.50 + 0.40 * (acwi_votes / 4.0)
        target_weights = pd.Series(
            {
                "ACWI": acwi_weight,
                "AGG": 0.0,
                "GLD": 1.0 - acwi_weight,
                "BSV": 0.0,
            }
        )
        eligible = ("ACWI", "GLD")

    target_weights = as_weight_series(target_weights)
    target_weights = target_weights.clip(lower=0, upper=1)
    target_weights = target_weights / target_weights.sum()
    bsv_floor = float(target_weights["BSV"])
    acwi_power_mode = False
    gld_phoenix_sleeve = False

    submitted_weights = target_weights
    turnover = None
    if previous_weights is not None:
        previous = as_weight_series(previous_weights)
        turnover = float((target_weights - previous).abs().sum())
        if turnover_limit is not None:
            submitted_weights = limit_total_allocation_change(
                previous,
                target_weights,
                limit=turnover_limit,
            )
            turnover = float((submitted_weights - previous).abs().sum())

    validate_weights(target_weights)
    validate_weights(submitted_weights)
    return AllocationDecision(
        signal_date=signal_date,
        target_weights=target_weights,
        submitted_weights=submitted_weights,
        metrics=metrics,
        eligible_assets=tuple(eligible),
        bsv_floor=bsv_floor,
        regime=regime,
        acwi_power_mode=acwi_power_mode,
        gld_phoenix_sleeve=gld_phoenix_sleeve,
        turnover_from_previous=turnover,
    )


def next_trading_day_after(index: pd.DatetimeIndex, date: pd.Timestamp) -> pd.Timestamp | None:
    """Return first trading date in index strictly after `date`."""

    pos = index.searchsorted(pd.Timestamp(date), side="right")
    if pos >= len(index):
        return None
    return pd.Timestamp(index[pos])


def previous_trading_day_on_or_before(
    index: pd.DatetimeIndex,
    date: pd.Timestamp,
) -> pd.Timestamp | None:
    """Return last trading date in index on or before `date`."""

    pos = index.searchsorted(pd.Timestamp(date), side="right") - 1
    if pos < 0:
        return None
    return pd.Timestamp(index[pos])


def generate_weekly_decisions(
    prices: pd.DataFrame,
    start: str = "2012-01-01",
    end: str | None = None,
    initial_weights: pd.Series | None = None,
    turnover_limit: float = 0.25,
) -> pd.DataFrame:
    """Generate Friday decisions for a historical backtest."""

    prices = prices.reindex(columns=ASSETS).dropna()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) if end else pd.Timestamp(prices.index[-1])
    friday_dates = pd.date_range(start=start_ts, end=end_ts, freq="W-FRI")

    previous = as_weight_series(initial_weights if initial_weights is not None else INITIAL_BACKTEST_WEIGHTS)
    rows: list[dict[str, object]] = []
    for decision_date in friday_dates:
        signal_date = previous_trading_day_on_or_before(
            prices.index,
            decision_date - pd.Timedelta(days=1),
        )
        application_date = next_trading_day_after(prices.index, decision_date)
        if signal_date is None or application_date is None:
            continue
        if signal_date < prices.index[260]:
            continue

        decision = compute_allocation_decision(
            prices,
            as_of=signal_date,
            previous_weights=previous,
            turnover_limit=turnover_limit,
        )
        previous = decision.submitted_weights
        row = {
            "decision_date": decision_date,
            "signal_date": decision.signal_date,
            "application_date": application_date,
            "eligible_assets": ",".join(decision.eligible_assets) or "BSV",
            "bsv_floor": decision.bsv_floor,
            "regime": decision.regime,
            "acwi_power_mode": decision.acwi_power_mode,
            "gld_phoenix_sleeve": decision.gld_phoenix_sleeve,
            "turnover": decision.turnover_from_previous,
        }
        row.update({asset: decision.submitted_weights[asset] for asset in ASSETS})
        rows.append(row)

    return pd.DataFrame(rows)


def max_drawdown(returns: pd.Series) -> float:
    """Compute max drawdown from a daily return series."""

    wealth = (1 + returns.fillna(0)).cumprod()
    drawdown = wealth / wealth.cummax() - 1
    return float(drawdown.min())


def performance_stats(returns: pd.Series) -> dict[str, float]:
    """Annualized performance summary using daily close-to-close returns."""

    returns = returns.dropna()
    if returns.empty:
        raise ValueError("Cannot compute performance stats for an empty return series.")
    wealth = (1 + returns).cumprod()
    annual_return = float(wealth.iloc[-1] ** (252 / len(returns)) - 1)
    annual_volatility = float(returns.std() * np.sqrt(252))
    sharpe = annual_return / annual_volatility if annual_volatility > 0 else np.nan
    return {
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_0_rf": float(sharpe),
        "max_drawdown": max_drawdown(returns),
        "total_return": float(wealth.iloc[-1] - 1),
        "final_wealth": float(wealth.iloc[-1]),
    }


def backtest(
    prices: pd.DataFrame,
    start: str = "2012-01-01",
    end: str | None = None,
    initial_weights: pd.Series | None = None,
    turnover_limit: float = 0.25,
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """Run the weekly strategy backtest.

    The simulation computes signals on the latest close before each Friday
    submission and applies the submitted weights from the next trading day.
    """

    prices = prices.reindex(columns=ASSETS).dropna()
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) if end else pd.Timestamp(prices.index[-1])
    decisions = generate_weekly_decisions(
        prices,
        start=start,
        end=end,
        initial_weights=initial_weights,
        turnover_limit=turnover_limit,
    )

    daily_weights = pd.DataFrame(index=prices.index, columns=ASSETS, dtype=float)
    current = as_weight_series(initial_weights if initial_weights is not None else INITIAL_BACKTEST_WEIGHTS)
    decision_iter = decisions.sort_values("application_date").iterrows()
    next_decision = next(decision_iter, None)
    for date in prices.index:
        while next_decision is not None and pd.Timestamp(next_decision[1]["application_date"]) <= date:
            current = as_weight_series(next_decision[1][list(ASSETS)])
            next_decision = next(decision_iter, None)
        daily_weights.loc[date] = current

    returns = prices.pct_change().fillna(0)
    strategy_returns = (daily_weights * returns).sum(axis=1).loc[start_ts:end_ts]
    daily_weights = daily_weights.loc[start_ts:end_ts]
    return strategy_returns, daily_weights, decisions


def write_submission_csv(
    weights: pd.Series,
    week_date: str,
    team_id: str = "TeamXX",
    output_dir: str | Path = "submissions",
) -> Path:
    """Write the exact one-row CSV format required by the guidelines."""

    weights = as_weight_series(weights)
    validate_weights(weights)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rounded = (weights * 100).round(2)
    rounded["BSV"] += 100.0 - float(rounded.sum())
    filename = f"{team_id}_{week_date}.csv"
    path = output_dir / filename
    row = {
        "week": week_date,
        "team_id": team_id,
        "acwi": rounded["ACWI"],
        "agg": rounded["AGG"],
        "gld": rounded["GLD"],
        "bsv": rounded["BSV"],
    }
    pd.DataFrame([row]).to_csv(path, index=False)
    return path
