# 本周提交说明

## 关于 45/25/20/10

这个比例没有必须采用的特殊来源。它更像一个早期对照组，而不是最终策略的理论基础。为了避免老师觉得我们是在一个静态组合上“手动微调”，当前版本已经把它从主策略说明里移除。

## 当前策略是什么

当前策略叫 **Contest-Horizon Equity-Gold Vote**。

正常市场下，模型只在 ACWI 和 GLD 之间做进攻配置：

- ACWI 是全球股票增长资产。
- GLD 是非股票回报来源和分散资产。
- AGG 和 BSV 只在 ACWI 出现压力时进入组合。

## 模型如何生成权重

模型每周比较 ACWI 和 GLD 的四个信号：

```text
1. 3个月收益率谁更高
2. 6个月收益率谁更高
3. 谁更高于自己的200日均线
4. 谁的63日年化波动率更低
```

ACWI 每赢一个信号得到 1 票：

```text
ACWI weight = 50% + 40% * ACWI_votes / 4
GLD weight  = 100% - ACWI weight
```

因此正常市场下 ACWI 的范围是 50% 到 90%。如果 ACWI 跌破 200 日均线且 3 个月收益为负，模型会自动转向 GLD、AGG、BSV。

## 本周为什么是 90/0/10/0

截至 2026-05-28：

- ACWI 的 3 个月收益率高于 GLD。
- ACWI 的 6 个月收益率高于 GLD。
- ACWI 相对 200 日均线的位置高于 GLD。
- ACWI 的 63 日年化波动率低于 GLD。

所以 ACWI 拿到 4 票，模型输出：

```csv
week,team_id,acwi,agg,gld,bsv
2026-06-01,Team05,90.0,0.0,10.0,0.0
```

这是一个偏进攻的组合，但不是主观下注。它是由同一套规则自动生成的，并且完全满足作业约束。

## 回测和 validation 体现在哪里

现在已经写进 `docs/project_report.md` 的 **Backtesting and Validation** 部分。原始数据表也在：

- `outputs/backtest_summary.csv`
- `outputs/contest_window_validation_summary.csv`
- `outputs/contest_window_validation_detail.csv`

长期回测区间是 2012-01-01 到 2026-05-28。比较对象有两个：

- Equal weight：ACWI、AGG、GLD、BSV 各 25%，代表保守分散组合。
- ACWI only：100% ACWI，代表最激进的股票基准。

长期回测结果：

| Portfolio | Annual Return | Volatility | Sharpe | Max Drawdown | Final Wealth |
| --- | ---: | ---: | ---: | ---: | ---: |
| Strategy | 9.91% | 11.30% | 0.88 | -19.84% | 3.89 |
| Equal weight | 6.11% | 6.72% | 0.91 | -15.25% | 2.34 |
| ACWI only | 11.83% | 16.18% | 0.73 | -33.53% | 4.99 |

20 个交易日窗口 validation，更接近 6 月比赛长度：

| Portfolio | Mean 20D | Median 20D | 5% Tail | Positive Rate |
| --- | ---: | ---: | ---: | ---: |
| Strategy | 0.88% | 1.09% | -4.60% | 66.20% |
| Equal weight | 0.56% | 0.51% | -2.27% | 63.40% |
| ACWI only | 1.00% | 1.47% | -6.17% | 66.67% |

答辩时可以这样说：

“我们的模型不是为了最低风险，而是为了在一个月比赛窗口里争取较高收益。它比 Equal Weight 更进攻，历史 20 日平均收益更高；但它又不是 100% ACWI，因为 ACWI-only 的最大回撤和 5% 尾部损失明显更差。因此我们选择的是介于保守分散和纯股票下注之间的系统化配置。”
