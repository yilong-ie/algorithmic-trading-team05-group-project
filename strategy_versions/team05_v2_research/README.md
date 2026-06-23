# Team05 V2 Research Version

This folder is an isolated research version for the group assignment. It does
not change the main project strategy files.

## Purpose

The goal is to test whether a more aggressive tactical allocation model could
improve the June live-performance component of the grade while still remaining
rule-based and explainable.

## Industry Models Reviewed

The research considered four common tactical asset allocation ideas:

- Time-series momentum / trend following.
- Dual momentum, combining relative and absolute momentum.
- Canary / protective allocation, switching defensive when risk assets weaken.
- Volatility management / risk budgeting.

References:

- Moskowitz, Ooi, and Pedersen, "Time Series Momentum":
  https://research.cbs.dk/en/publications/time-series-momentum
- Antonacci, "Risk Premia Harvesting Through Dual Momentum":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750
- Keller and Keuning, "Defensive Asset Allocation":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3212862
- Moreira and Muir, "Volatility Managed Portfolios":
  https://www.nber.org/papers/w22208

## Candidate Model

The selected experimental model is **aggressive_vote_v2**. It keeps the same
ACWI-vs-GLD vote structure as the main model:

```text
1. 3-month return
2. 6-month return
3. 200-day trend gap
4. 63-day volatility, lower is better
```

The difference is the normal-regime weight scale:

```text
ACWI weight = 40% + 15% * ACWI_votes
GLD weight  = 100% - ACWI weight
```

If ACWI wins all four votes, V2 submits 100% ACWI. If ACWI enters stress, the
same defensive rotation logic as the main model applies.

## Result

Using data through 2026-05-28, V2 submits:

```csv
week,team_id,acwi,agg,gld,bsv
2026-06-01,Team05,100.0,0.0,0.0,0.0
```

## Recommendation

V2 is appropriate only if the team wants the highest live upside and accepts a
more aggressive risk posture. The main model remains more balanced and easier to
defend as an allocation system because it keeps a small GLD diversifier.

## Files

| File | Purpose |
| --- | --- |
| `compare_v2_models.py` | Runs model comparison and writes outputs |
| `outputs/candidate_model_comparison.csv` | Backtest and 20-day validation comparison |
| `outputs/selected_v2_weights.csv` | V2 selected weights |
| `submissions/Team05_2026-06-01.csv` | V2 CSV submission candidate |

## Run

From the project root:

```powershell
python strategy_versions\team05_v2_research\compare_v2_models.py
```
