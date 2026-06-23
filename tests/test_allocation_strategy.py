import unittest

import numpy as np
import pandas as pd

from src.allocation_strategy import (
    ASSETS,
    compute_allocation_decision,
    limit_total_allocation_change,
    validate_weights,
)


def synthetic_prices(rows: int = 260) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=rows)
    trend = np.linspace(1.0, 1.3, rows)
    data = {
        "ACWI": 100 * trend,
        "AGG": 100 * np.linspace(1.0, 1.03, rows),
        "GLD": 100 * np.linspace(1.0, 0.95, rows),
        "BSV": 100 * np.linspace(1.0, 1.01, rows),
    }
    return pd.DataFrame(data, index=dates)


class AllocationStrategyTests(unittest.TestCase):
    def test_turnover_limit_uses_total_allocation_change(self) -> None:
        previous = pd.Series([0.25, 0.25, 0.25, 0.25], index=ASSETS)
        target = pd.Series([0.70, 0.00, 0.00, 0.30], index=ASSETS)
        limited = limit_total_allocation_change(previous, target, limit=0.25)

        self.assertAlmostEqual(float((limited - previous).abs().sum()), 0.25)
        self.assertAlmostEqual(float(limited.sum()), 1.0)
        self.assertTrue((limited >= 0).all())

    def test_model_decision_satisfies_project_constraints(self) -> None:
        decision = compute_allocation_decision(synthetic_prices())
        validate_weights(decision.submitted_weights)
        self.assertAlmostEqual(float(decision.submitted_weights.sum()), 1.0)
        self.assertTrue((decision.submitted_weights >= 0).all())
        self.assertTrue((decision.submitted_weights <= 1).all())

    def test_normal_regime_vote_model_is_deterministic(self) -> None:
        decision = compute_allocation_decision(synthetic_prices())

        self.assertEqual(decision.regime, "contest-horizon equity-gold vote")
        self.assertAlmostEqual(float(decision.target_weights["ACWI"]), 0.80)
        self.assertAlmostEqual(float(decision.target_weights["GLD"]), 0.20)
        self.assertAlmostEqual(float(decision.target_weights["AGG"]), 0.00)
        self.assertAlmostEqual(float(decision.target_weights["BSV"]), 0.00)


if __name__ == "__main__":
    unittest.main()
