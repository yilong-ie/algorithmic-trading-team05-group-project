"""Run the allocation model, backtest it, and create the weekly CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.allocation_strategy import (
    ASSETS,
    compute_allocation_decision,
    fetch_adjusted_close,
    performance_stats,
    backtest,
    write_submission_csv,
)


def parse_previous_weights(value: str | None) -> pd.Series | None:
    """Parse comma-separated percentage weights in ACWI,AGG,GLD,BSV order."""

    if value is None:
        return None
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("Use four comma-separated weights: ACWI,AGG,GLD,BSV.")
    return pd.Series([part / 100 for part in parts], index=ASSETS)


def next_monday(today: pd.Timestamp | None = None) -> str:
    """Default week label for the upcoming live allocation week."""

    today = pd.Timestamp.today().normalize() if today is None else today.normalize()
    days_ahead = (7 - today.weekday()) % 7
    days_ahead = 7 if days_ahead == 0 else days_ahead
    return (today + pd.Timedelta(days=days_ahead)).strftime("%Y-%m-%d")


def save_backtest_chart(
    strategy_returns: pd.Series,
    benchmark_returns: pd.DataFrame,
    output_dir: Path,
) -> None:
    """Save equity curve and drawdown charts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    curves = pd.concat(
        {
            "Strategy": (1 + strategy_returns).cumprod(),
            "Equal weight": (1 + benchmark_returns["equal_weight"]).cumprod(),
            "ACWI only": (1 + benchmark_returns["acwi_only"]).cumprod(),
        },
        axis=1,
    )

    plt.figure(figsize=(10, 6))
    curves.plot(ax=plt.gca(), linewidth=1.8)
    plt.title("Backtest Growth of $1")
    plt.ylabel("Wealth")
    plt.xlabel("")
    plt.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_dir / "equity_curve.png", dpi=160)
    plt.close()

    drawdowns = curves / curves.cummax() - 1
    plt.figure(figsize=(10, 5))
    drawdowns.plot(ax=plt.gca(), linewidth=1.5)
    plt.title("Backtest Drawdown")
    plt.ylabel("Drawdown")
    plt.xlabel("")
    plt.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_dir / "drawdown.png", dpi=160)
    plt.close()


def save_allocation_chart(weights: pd.DataFrame, output_dir: Path) -> None:
    """Save stacked allocation history."""

    output_dir.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(11, 5.5))
    (weights * 100).plot.area(ax=plt.gca(), linewidth=0)
    plt.title("Strategy Allocation History")
    plt.ylabel("Weight (%)")
    plt.xlabel("")
    plt.ylim(0, 100)
    plt.tight_layout()
    plt.savefig(output_dir / "allocation_history.png", dpi=160)
    plt.close()


def save_contest_window_validation(prices: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    """Validate strategies on 20-trading-day windows similar to the live contest."""

    rows: list[dict[str, float]] = []
    equal_weights = pd.Series(0.25, index=ASSETS)
    acwi_only = pd.Series({"ACWI": 1.0, "AGG": 0.0, "GLD": 0.0, "BSV": 0.0})

    for signal_pos in range(260, len(prices) - 22, 5):
        signal_prices = prices.iloc[: signal_pos + 1]
        decision = compute_allocation_decision(
            signal_prices,
            previous_weights=None,
            turnover_limit=None,
        )
        forward_returns = prices.iloc[signal_pos + 21] / prices.iloc[signal_pos + 1] - 1
        rows.append(
            {
                "signal_date": prices.index[signal_pos],
                "strategy": float((decision.target_weights * forward_returns).sum()),
                "equal_weight": float((equal_weights * forward_returns).sum()),
                "acwi_only": float((acwi_only * forward_returns).sum()),
            }
        )

    validation = pd.DataFrame(rows)
    summary_rows = []
    for column in ["strategy", "equal_weight", "acwi_only"]:
        series = validation[column]
        summary_rows.append(
            {
                "portfolio": column,
                "mean_20d_return": series.mean(),
                "median_20d_return": series.median(),
                "p05_20d_return": series.quantile(0.05),
                "p25_20d_return": series.quantile(0.25),
                "positive_window_rate": (series > 0).mean(),
            }
        )
    summary = pd.DataFrame(summary_rows).set_index("portfolio")
    validation.to_csv(output_dir / "contest_window_validation_detail.csv", index=False)
    summary.to_csv(output_dir / "contest_window_validation_summary.csv")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Dynamic ETF allocation project runner.")
    parser.add_argument("--team-id", default="TeamXX", help="Team ID used in the submission CSV.")
    parser.add_argument(
        "--week-date",
        default=next_monday(),
        help="Week label for the CSV, e.g. 2026-06-01.",
    )
    parser.add_argument("--as-of", default=None, help="Signal date cutoff, e.g. 2026-05-28.")
    parser.add_argument(
        "--previous-weights",
        default=None,
        help="Optional previous submitted weights as percentages: ACWI,AGG,GLD,BSV.",
    )
    parser.add_argument("--start", default="2012-01-01", help="Backtest start date.")
    parser.add_argument("--output-dir", default="outputs", help="Directory for charts and tables.")
    parser.add_argument("--submission-dir", default="submissions", help="Directory for weekly CSV.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_weights = parse_previous_weights(args.previous_weights)

    prices = fetch_adjusted_close()
    prices.to_csv(output_dir / "adjusted_close_prices.csv")

    decision = compute_allocation_decision(
        prices,
        as_of=args.as_of,
        previous_weights=previous_weights,
        turnover_limit=0.25 if previous_weights is not None else None,
    )

    decision.metrics.to_csv(output_dir / "latest_signal_snapshot.csv")
    pd.DataFrame(
        {
            "target_weight": decision.target_weights,
            "submitted_weight": decision.submitted_weights,
            "submitted_weight_pct": decision.submitted_weights * 100,
        }
    ).to_csv(output_dir / "latest_weights.csv")

    strategy_returns, daily_weights, weekly_decisions = backtest(
        prices,
        start=args.start,
        end=args.as_of,
    )
    asset_returns = prices.pct_change().fillna(0)
    equal_weight_returns = asset_returns.mul(0.25).sum(axis=1).loc[strategy_returns.index]
    acwi_only_returns = asset_returns["ACWI"].loc[strategy_returns.index]
    benchmark_returns = pd.DataFrame(
        {
            "equal_weight": equal_weight_returns,
            "acwi_only": acwi_only_returns,
        }
    )

    summary = pd.DataFrame(
        {
            "strategy": performance_stats(strategy_returns),
            "equal_weight": performance_stats(equal_weight_returns),
            "acwi_only": performance_stats(acwi_only_returns),
        }
    ).T
    summary.to_csv(output_dir / "backtest_summary.csv")
    pd.concat(
        {"strategy": strategy_returns, **{col: benchmark_returns[col] for col in benchmark_returns}},
        axis=1,
    ).to_csv(output_dir / "backtest_daily_returns.csv")
    daily_weights.to_csv(output_dir / "backtest_daily_weights.csv")
    weekly_decisions.to_csv(output_dir / "backtest_weekly_decisions.csv", index=False)

    save_backtest_chart(strategy_returns, benchmark_returns, output_dir)
    save_allocation_chart(daily_weights, output_dir)
    contest_summary = save_contest_window_validation(prices, output_dir)
    submission_path = write_submission_csv(
        decision.submitted_weights,
        week_date=args.week_date,
        team_id=args.team_id,
        output_dir=args.submission_dir,
    )

    print(f"Signal date: {decision.signal_date.date()}")
    print(f"Regime: {decision.regime}")
    print(f"Eligible assets: {', '.join(decision.eligible_assets) or 'BSV only'}")
    print("Submitted weights (%):")
    print((decision.submitted_weights * 100).round(2).to_string())
    print(f"Submission CSV: {submission_path}")
    print("Backtest summary:")
    display_summary = summary.copy()
    percent_columns = [
        "annual_return",
        "annual_volatility",
        "max_drawdown",
        "total_return",
    ]
    display_summary[percent_columns] = display_summary[percent_columns] * 100
    print(display_summary.round(2).to_string())
    print("20-trading-day contest window validation:")
    print((contest_summary * 100).round(2).to_string())


if __name__ == "__main__":
    main()
