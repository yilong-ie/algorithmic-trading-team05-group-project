# Dynamic Asset Allocation Competition

This repository contains a reproducible rule-based ETF allocation system for the
Algorithmic Trading group project.

## Current Strategy

The model is a **Contest-Horizon Equity-Gold Vote**. It is not built from a
static 45/25/20/10 allocation. That portfolio was only a benchmark in the first
draft, and it has been removed from the current weekly workflow to avoid
confusion.

The live competition is short, from 2026-06-01 to 2026-06-29, so the model is
intentionally return-seeking in normal markets. It uses ACWI as the main growth
asset and GLD as the main diversifier. AGG and BSV are used only when the model
detects equity stress.

## Weekly Rule

Every Friday, the model computes signals using the latest available adjusted
close prices for the four permitted ETFs:

- ACWI: 3-month return, 6-month return, 200-day trend, 63-day volatility.
- GLD: same four signals.
- AGG and BSV: used in defensive stress regimes.

In a normal equity regime, four equal votes decide the ACWI/GLD mix:

```text
ACWI gets one vote if its 3M return is higher than GLD.
ACWI gets one vote if its 6M return is higher than GLD.
ACWI gets one vote if its 200D trend gap is higher than GLD.
ACWI gets one vote if its 63D volatility is lower than GLD.

ACWI weight = 50% + 40% * ACWI_votes / 4
GLD weight  = 100% - ACWI weight
```

This means ACWI ranges from 50% to 90% during normal markets. If ACWI is below
its 200-day average and has negative 3-month return, the model mechanically
rotates toward GLD, AGG, and BSV.

## This Week's Submission

Using data through **2026-05-28**, the model allocation for the week beginning
2026-06-01 is:

 ```csv
week,team_id,acwi,agg,gld,bsv
2026-06-01,Team05,90.0,0.0,10.0,0.0
```

Required email subject:

```text
Algorithmic Trading Project | Team 05 | Portfolio for Week 2026-06-01
```

## How To Run

### Classroom Demo From GitHub

On a new classroom computer, clone the repository first. The commands below are
the safest live-demo sequence because they start from an empty folder and use a
fixed final submission date.

```powershell
cd "D:\Desktop\New_folder"
git clone https://github.com/yilong-ie/algorithmic-trading-team05-group-project.git
cd algorithmic-trading-team05-group-project
```

Then create the virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell blocks environment activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Run the final live-submission example:

```powershell
python run_strategy.py --team-id Team05 --week-date 2026-06-26 --as-of 2026-06-27 --previous-weights 90,0,10,0
```

The generated CSV will be:

```text
submissions/Team05_2026-06-26.csv
```

Do not run `python run_strategy.py` without arguments during the live demo,
because the default date may not match the professor's required Friday-date
format.

### Local Setup

Create and activate a virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS/Linux, use:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
```

Generate the first submission file and backtest outputs:

```powershell
python run_strategy.py --team-id Team05 --week-date 2026-06-01 --as-of 2026-05-28
```

If your system uses `python3`, run the same command as:

```bash
python3 run_strategy.py --team-id Team05 --week-date 2026-06-01 --as-of 2026-05-28
```

For later weekly submissions, pass the previous submitted weights so the 25
percentage point rebalance rule is enforced:

```powershell
python run_strategy.py --team-id Team05 --week-date 2026-06-08 --previous-weights 90,0,10,0
```

## Main Outputs

| File | Purpose |
| --- | --- |
| `submissions/Team05_2026-06-01.csv` | One-row CSV in the required submission format |
| `outputs/latest_weights.csv` | Target and submitted model weights |
| `outputs/latest_signal_snapshot.csv` | Current signal values used by the model |
| `outputs/backtest_summary.csv` | Main performance statistics |
| `outputs/contest_window_validation_summary.csv` | 20-trading-day validation aligned with the live contest horizon |

## Validation

Run tests:

```powershell
python -m unittest discover -s tests
```
