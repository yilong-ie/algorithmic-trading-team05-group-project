"""Research alternative group-project allocation models without changing v1."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.allocation_strategy import (  # noqa: E402
    ASSETS,
    compute_allocation_decision,
    fetch_adjusted_close,
    limit_total_allocation_change,
    performance_stats,
    validate_weights,
    write_submission_csv,
)


OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
SUBMISSION_DIR = Path(__file__).resolve().parent / "submissions"


def normalize(weights: pd.Series | dict[str, float]) -> pd.Series:
    out = pd.Series(weights, index=ASSETS).astype(float).clip(lower=0)
    if out.sum() <= 0:
        out["BSV"] = 1.0
    out = out / out.sum()
    validate_weights(out)
    return out


def signal_frame(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.reindex(columns=ASSETS).dropna()
    last = prices.iloc[-1]
    signals = pd.DataFrame(index=ASSETS)
    signals["return_1m"] = last / prices.iloc[-22] - 1
    signals["return_3m"] = last / prices.iloc[-64] - 1
    signals["return_6m"] = last / prices.iloc[-127] - 1
    signals["return_12m"] = last / prices.iloc[-253] - 1
    signals["trend_gap_200d"] = last / prices.rolling(200).mean().iloc[-1] - 1
    signals["volatility_63d"] = prices.pct_change().tail(63).std() * np.sqrt(252)
    return signals


def current_vote(prices: pd.DataFrame) -> pd.Series:
    return compute_allocation_decision(prices, turnover_limit=None).target_weights


def equal_weight(_: pd.DataFrame) -> pd.Series:
    return pd.Series(0.25, index=ASSETS)


def acwi_only(_: pd.DataFrame) -> pd.Series:
    return normalize({"ACWI": 1.0, "AGG": 0.0, "GLD": 0.0, "BSV": 0.0})


def dual_momentum_12m(prices: pd.DataFrame) -> pd.Series:
    signals = signal_frame(prices)
    winner = signals.loc[["ACWI", "GLD"], "return_12m"].idxmax()
    if (
        signals.loc[winner, "return_12m"] > signals.loc["BSV", "return_12m"]
        and signals.loc[winner, "trend_gap_200d"] > 0
    ):
        return normalize({asset: 1.0 if asset == winner else 0.0 for asset in ASSETS})
    defensive = signals.loc[["AGG", "BSV"], "return_12m"].idxmax()
    return normalize({asset: 1.0 if asset == defensive else 0.0 for asset in ASSETS})


def protective_momentum(prices: pd.DataFrame) -> pd.Series:
    """Simple canary-style model adapted to the four allowed ETFs.

    If ACWI's trend is healthy, allocate to the top two assets by blended
    momentum. If ACWI is in stress, use the stronger defensive ETF.
    """

    signals = signal_frame(prices)
    acwi_healthy = signals.loc["ACWI", "trend_gap_200d"] > 0 and signals.loc["ACWI", "return_3m"] > 0
    if not acwi_healthy:
        defensive = signals.loc[["AGG", "BSV"], "return_3m"].idxmax()
        return normalize({asset: 1.0 if asset == defensive else 0.0 for asset in ASSETS})

    score = (
        signals["return_1m"].rank(pct=True)
        + signals["return_3m"].rank(pct=True)
        + signals["return_6m"].rank(pct=True)
        + signals["trend_gap_200d"].rank(pct=True)
    ) / 4
    selected = score.sort_values(ascending=False).head(2).index
    raw = score[selected] / signals.loc[selected, "volatility_63d"].clip(lower=1e-6)
    weights = pd.Series(0.0, index=ASSETS)
    weights[selected] = raw / raw.sum()
    return normalize(weights)


def aggressive_vote_v2(prices: pd.DataFrame) -> pd.Series:
    """More aggressive version of the current vote model.

    It keeps the same four transparent ACWI-vs-GLD votes, but lets the winner
    receive up to 100% in a normal regime. This is the only candidate that would
    change the first live submission.
    """

    signals = signal_frame(prices)
    acwi_stress = signals.loc["ACWI", "trend_gap_200d"] < 0 and signals.loc["ACWI", "return_3m"] < 0
    gld_stress = signals.loc["GLD", "trend_gap_200d"] < 0 and signals.loc["GLD", "return_3m"] < 0
    gld_supportive = signals.loc["GLD", "trend_gap_200d"] > 0 and signals.loc["GLD", "return_6m"] > 0

    if acwi_stress and gld_stress:
        return normalize({"ACWI": 0.20, "AGG": 0.25, "GLD": 0.15, "BSV": 0.40})
    if acwi_stress and gld_supportive:
        return normalize({"ACWI": 0.25, "AGG": 0.10, "GLD": 0.55, "BSV": 0.10})
    if acwi_stress:
        return normalize({"ACWI": 0.25, "AGG": 0.25, "GLD": 0.20, "BSV": 0.30})

    acwi_votes = 0
    acwi_votes += signals.loc["ACWI", "return_3m"] > signals.loc["GLD", "return_3m"]
    acwi_votes += signals.loc["ACWI", "return_6m"] > signals.loc["GLD", "return_6m"]
    acwi_votes += signals.loc["ACWI", "trend_gap_200d"] > signals.loc["GLD", "trend_gap_200d"]
    acwi_votes += signals.loc["ACWI", "volatility_63d"] < signals.loc["GLD", "volatility_63d"]

    acwi_weight = 0.40 + 0.15 * float(acwi_votes)
    return normalize({"ACWI": acwi_weight, "AGG": 0.0, "GLD": 1.0 - acwi_weight, "BSV": 0.0})


MODELS = {
    "current_vote_v1": current_vote,
    "aggressive_vote_v2": aggressive_vote_v2,
    "acwi_only": acwi_only,
    "dual_momentum_12m": dual_momentum_12m,
    "protective_momentum": protective_momentum,
    "equal_weight": equal_weight,
}


def backtest_model(
    prices: pd.DataFrame,
    model_name: str,
    start: str = "2012-01-01",
    turnover_limit: float = 0.25,
) -> pd.Series:
    model = MODELS[model_name]
    returns = prices.pct_change().fillna(0)
    fridays = pd.date_range(start=start, end=prices.index[-1], freq="W-FRI")
    previous = pd.Series(0.25, index=ASSETS)
    decisions: list[tuple[pd.Timestamp, pd.Series]] = []

    for decision_date in fridays:
        signal_pos = prices.index.searchsorted(decision_date - pd.Timedelta(days=1), side="right") - 1
        application_pos = prices.index.searchsorted(decision_date, side="right")
        if signal_pos < 260 or application_pos >= len(prices):
            continue
        target = model(prices.iloc[: signal_pos + 1])
        submitted = limit_total_allocation_change(previous, target, limit=turnover_limit)
        decisions.append((pd.Timestamp(prices.index[application_pos]), submitted))
        previous = submitted

    weights = pd.DataFrame(index=prices.index, columns=ASSETS, dtype=float)
    current = pd.Series(0.25, index=ASSETS)
    decision_iter = iter(decisions)
    next_decision = next(decision_iter, None)
    for date in prices.index:
        while next_decision is not None and next_decision[0] <= date:
            current = next_decision[1]
            next_decision = next(decision_iter, None)
        weights.loc[date] = current

    return (weights * returns).sum(axis=1).loc[pd.Timestamp(start) :]


def contest_window_stats(prices: pd.DataFrame, model_name: str) -> dict[str, float]:
    model = MODELS[model_name]
    values = []
    for signal_pos in range(260, len(prices) - 22, 5):
        weights = model(prices.iloc[: signal_pos + 1])
        forward_returns = prices.iloc[signal_pos + 21] / prices.iloc[signal_pos + 1] - 1
        values.append(float((weights * forward_returns).sum()))
    series = pd.Series(values)
    return {
        "mean_20d_return": float(series.mean()),
        "median_20d_return": float(series.median()),
        "p05_20d_return": float(series.quantile(0.05)),
        "positive_window_rate": float((series > 0).mean()),
        "worst_20d_return": float(series.min()),
        "best_20d_return": float(series.max()),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)

    prices = fetch_adjusted_close(end="2026-05-29")
    prices.to_csv(OUTPUT_DIR / "adjusted_close_prices.csv")

    rows = []
    for model_name in MODELS:
        returns = backtest_model(prices, model_name)
        row = {"model": model_name}
        row.update(performance_stats(returns))
        row.update(contest_window_stats(prices, model_name))
        current_weights = MODELS[model_name](prices)
        row.update({f"current_{asset.lower()}": float(current_weights[asset]) for asset in ASSETS})
        rows.append(row)

    comparison = pd.DataFrame(rows).sort_values(
        ["mean_20d_return", "p05_20d_return"],
        ascending=[False, False],
    )
    comparison.to_csv(OUTPUT_DIR / "candidate_model_comparison.csv", index=False)

    selected = MODELS["aggressive_vote_v2"](prices)
    write_submission_csv(
        selected,
        week_date="2026-06-01",
        team_id="Team05",
        output_dir=SUBMISSION_DIR,
    )
    pd.DataFrame(
        {
            "submitted_weight": selected,
            "submitted_weight_pct": selected * 100,
        }
    ).to_csv(OUTPUT_DIR / "selected_v2_weights.csv")

    display = comparison.copy()
    for col in [
        "annual_return",
        "annual_volatility",
        "max_drawdown",
        "total_return",
        "mean_20d_return",
        "median_20d_return",
        "p05_20d_return",
        "positive_window_rate",
        "worst_20d_return",
        "best_20d_return",
        "current_acwi",
        "current_agg",
        "current_gld",
        "current_bsv",
    ]:
        display[col] = display[col] * 100
    print(display.round(2).to_string(index=False))
    print("\\nSelected v2 submission:")
    print((selected * 100).round(2).to_string())


if __name__ == "__main__":
    main()
