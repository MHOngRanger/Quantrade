# Binance Leg TOPN Research

## Purpose

Compare allocation rules for the Binance funding-rate leg while assuming the
IBKR leg is a perfect delta hedge.

## Data And Backtest Setup

- Data source: Binance USD-M public funding-rate history.
- Symbol pool: `TRADFI_SYMBOLS`, 31 Binance TradFi USDT perpetual contracts.
- Cache handling: deleted `data/*_funding.parquet`, then refreshed all symbols.
- Sample: `2026-01-01 00:00 UTC` to `2026-04-26 00:00 UTC`.
- Initial equity: `$1,000,000`.
- Signal threshold: `abs(funding_rate) > 0.0001` per 8h period.
- Binance leverage: `5x`.
- Costs: Binance futures fees only, using the default cost model.
- IBKR: assumed perfect hedge, no slippage, no borrow cost, no option spread,
  no margin friction.

## Strategy Mechanics

At each funding interval:

1. Read the available funding rates for all active symbols.
2. Keep symbols whose absolute funding rate is above the threshold.
3. For positive funding, short the Binance perpetual.
4. For negative funding, long the Binance perpetual.
5. For TOPN variants, rank candidates by `abs(funding_rate)` and keep the top N.
6. Allocate notional either by `abs(funding_rate)` weight or equal weight.
7. Notional exposure is `equity * weight * leverage`.
8. Close positions whose signal disappears; flip positions when the funding
   sign changes.

The existing backtest evaluates signals on each 8h funding timestamp. This is
useful for ranking rule comparison, but it is optimistic for live execution
because it assumes the rate can be observed and traded without timing friction.

## Results

| Rule | Net Profit | Total Return | Annualized Return | Sharpe | Max Drawdown | Trades |
|---|---:|---:|---:|---:|---:|---:|
| Top2 abs-weighted | `$2,441,788` | `244.18%` | `4,897.8%` | `11.24` | `-2.73%` | `519` |
| Top3 abs-weighted | `$2,118,817` | `211.88%` | `3,558.9%` | `10.86` | `-2.82%` | `670` |
| Top2 equal-weighted | `$2,076,320` | `207.63%` | `3,403.4%` | `10.54` | `-2.89%` | `519` |
| Top5 abs-weighted | `$2,008,281` | `200.83%` | `3,164.0%` | `11.41` | `-2.20%` | `845` |
| Top8 abs-weighted | `$1,896,126` | `189.61%` | `2,794.2%` | `12.13` | `-2.00%` | `971` |
| Top10 abs-weighted | `$1,849,218` | `184.92%` | `2,648.5%` | `12.19` | `-2.00%` | `1034` |
| Top1 | `$1,824,626` | `182.46%` | `2,574.1%` | `10.14` | `-2.40%` | `350` |
| All signals abs-weighted | `$1,784,536` | `178.45%` | `2,455.8%` | `13.06` | `-2.00%` | `1097` |
| Top3 equal-weighted | `$1,665,066` | `166.51%` | `2,124.6%` | `9.54` | `-3.03%` | `670` |
| Fixed all equities abs-weighted | `$1,495,916` | `149.59%` | `1,707.7%` | `11.29` | `-2.46%` | `713` |
| Fixed liquid IBKR 12 abs-weighted | `$1,139,665` | `113.97%` | `1,010.3%` | `9.15` | `-2.40%` | `344` |
| Top5 equal-weighted | `$1,229,582` | `122.96%` | `1,164.8%` | `9.30` | `-2.35%` | `845` |
| All signals equal-weighted | `$671,414` | `67.14%` | `408.2%` | `8.94` | `-2.26%` | `1097` |
| Fixed commodities abs-weighted | `$418,575` | `41.86%` | `202.4%` | `7.88` | `-6.81%` | `384` |

## Single-Symbol Diagnostic

The highest in-sample single-symbol contributors were:

| Symbol | Net Profit | Total Return | Sharpe | Max Drawdown | Trades |
|---|---:|---:|---:|---:|---:|
| MSTRUSDT | `$1,113,623` | `111.36%` | `7.15` | `-1.13%` | `69` |
| COINUSDT | `$873,490` | `87.35%` | `6.72` | `-0.88%` | `55` |
| CRCLUSDT | `$760,815` | `76.08%` | `7.30` | `-0.86%` | `70` |
| HOODUSDT | `$412,436` | `41.24%` | `5.40` | `-1.81%` | `69` |
| EWYUSDT | `$389,243` | `38.92%` | `5.71` | `-1.37%` | `43` |
| PLTRUSDT | `$377,310` | `37.73%` | `6.49` | `-1.03%` | `30` |

These single-symbol results are diagnostic only. They should not be converted
directly into a fixed winner basket because that would overfit the sample.

## Interpretation

- Pure return ranking favors `Top2` and `Top3`, but these variants are more
  concentrated and more dependent on extreme funding events.
- `All signals abs-weighted` has the highest Sharpe in this sample, but it
  dilutes exposure into weaker signals.
- Equal weighting materially underperforms abs-weighting across comparable
  variants.
- Fixed baskets are useful for execution constraints, but they underperform
  dynamic TOPN selection in this sample.

Preferred research candidates:

1. `Top5 abs-weighted`: aggressive balance between concentration and breadth.
2. `Top8 abs-weighted`: more diversified, still close to the all-signal Sharpe.

## Liquidation Stress Addendum

This pass adds a Binance-leg liquidation stress check using Binance 8h kline
data for all 31 symbols.

Method:

1. Use the same funding signal and allocation logic as the main comparison.
2. For each 8h holding window, use kline `open/high/low` to estimate the
   maximum adverse move after entry.
3. For short perpetual positions, adverse move is `high / open - 1`.
4. For long perpetual positions, adverse move is `1 - low / open`.
5. Simplified liquidation threshold is:

   `1 / leverage - maintenance_margin_rate`

   with `maintenance_margin_rate = 1%`.
6. At 5x leverage this gives a simplified liquidation zone at roughly `19%`
   adverse movement.
7. Also compute a cross-margin style stress ratio:

   `sum(adverse_move * notional) / sum(notional / leverage)`

   This estimates how much Binance initial margin would be consumed if each
   held symbol reached its intra-window adverse extreme.

This is a conservative path-risk screen, not an exact Binance liquidation-price
engine. Exact liquidation depends on symbol-specific maintenance tiers, fee
buffers, position mode, cross vs isolated margin, wallet balance, and live
mark-price mechanics.

### 5x Liquidation Stress Results

| Rule | Net Profit | Max Symbol Adverse Move | Liquidation Breaches | 75% Near-Breaches | Max Portfolio Margin Used |
|---|---:|---:|---:|---:|---:|
| Top2 abs-weighted | `$2,441,788` | `21.25%` | `3` | `2` | `97.44%` |
| Top3 abs-weighted | `$2,118,817` | `21.25%` | `3` | `2` | `83.12%` |
| Top5 abs-weighted | `$2,008,281` | `21.25%` | `2` | `2` | `71.12%` |
| Top8 abs-weighted | `$1,896,126` | `21.25%` | `2` | `2` | `66.48%` |
| All signals abs-weighted | `$1,784,536` | `21.25%` | `3` | `2` | `66.48%` |

Worst 5x events:

| Timestamp UTC | Symbol | Direction | Adverse Move | Notes |
|---|---|---:|---:|---|
| `2026-02-25 08:00` | `CRCLUSDT` | short | `21.25%` | Above simplified 5x liquidation zone |
| `2026-04-07 16:00` | `CLUSDT` | long | `20.62%` | Above simplified 5x liquidation zone |
| `2026-03-02 08:00` | `CRCLUSDT` | short | `19.04%` | Borderline breach in Top2/Top3/all-signal variants |
| `2026-02-05 00:00` | `XAGUSDT` | long | `17.37%` | Near-breach at 5x |
| `2026-04-07 16:00` | `BZUSDT` | long | `16.35%` | Near-breach at 5x |

The strongest warning is not the strategy-level drawdown. The PnL curve remains
smooth because the IBKR leg is assumed to hedge delta perfectly. The practical
problem is venue-level margin: Binance can liquidate the perpetual leg before
IBKR gains can be moved over as collateral.

### Leverage Sensitivity With Liquidation Screen

| Rule | Leverage | Simplified Liq Move | Net Profit | Total Return | Max Symbol Adverse | Liquidation Breaches | 75% Near-Breaches | Max Portfolio Margin Used |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Top5 | `3x` | `32.33%` | `$943,268` | `94.33%` | `21.25%` | `0` | `0` | `42.67%` |
| Top8 | `3x` | `32.33%` | `$898,354` | `89.84%` | `21.25%` | `0` | `0` | `39.89%` |
| All | `3x` | `32.33%` | `$853,111` | `85.31%` | `21.25%` | `0` | `0` | `39.89%` |
| Top5 | `4x` | `24.00%` | `$1,419,228` | `141.92%` | `21.25%` | `0` | `2` | `56.89%` |
| Top8 | `4x` | `24.00%` | `$1,345,889` | `134.59%` | `21.25%` | `0` | `2` | `53.19%` |
| All | `4x` | `24.00%` | `$1,272,476` | `127.25%` | `21.25%` | `0` | `3` | `53.19%` |
| Top5 | `5x` | `19.00%` | `$2,008,281` | `200.83%` | `21.25%` | `2` | `2` | `71.12%` |
| Top8 | `5x` | `19.00%` | `$1,896,126` | `189.61%` | `21.25%` | `2` | `2` | `66.48%` |
| All | `5x` | `19.00%` | `$1,784,536` | `178.45%` | `21.25%` | `3` | `2` | `66.48%` |

Risk-adjusted interpretation:

- `5x` is too aggressive if Binance collateral is not actively topped up.
  It shows explicit simplified liquidation breaches.
- `4x` avoids breaches in this sample but still has near-breach events, so it
  needs a real-time collateral buffer and emergency deleveraging.
- `3x` is much cleaner on this sample: no breach and no 75% near-breach, while
  still producing a high theoretical return.
- With liquidation risk prioritized, the preferred rule changes from
  `Top5/Top8 at 5x` to `Top5 or Top8 at 3x-4x`.

Current practical preference:

1. `Top8 abs-weighted at 3x` if the priority is avoiding forced liquidation.
2. `Top5 abs-weighted at 4x` if accepting higher collateral risk for higher
   expected return.
3. Avoid `5x` unless Binance has unused collateral beyond the strategy's
   nominal margin allocation and automatic deleveraging is implemented.

## Aggressive Sizing Update

After reviewing the Binance TradFi structure, the previous liquidation stress
should be read as a conservative last-trade-price stress, not a precise
liquidation model.

Important clarification:

- Binance liquidation is driven by mark price and margin, not raw last-trade
  kline highs/lows.
- If the non-US-session mark price is constrained by a hard deviation cap such
  as roughly `3%`, then overnight Binance liquidation risk is much lower than
  the 8h high/low stress table suggests.
- A stock open gap is not automatically a strategy loss when the IBKR hedge
  tracks the same underlying exposure. Binance may gap against one leg, while
  the IBKR synthetic hedge should gap in the offsetting direction.
- The real residual risks are basis, execution timing, option spread, hedge
  tracking error, and account-level collateral separation.

Under that interpretation, it is reasonable to consider a more aggressive
allocation than the liquidation-first recommendation above.

### Aggressive Candidate Set

| Rule | Leverage | Net Profit | Total Return | Sharpe | Max Drawdown | Trades | Comment |
|---|---:|---:|---:|---:|---:|---:|---|
| Top2 abs-weighted | `5x` | `$2,441,788` | `244.18%` | `11.24` | `-2.73%` | `519` | Highest return, highest concentration |
| Top3 abs-weighted | `5x` | `$2,118,817` | `211.88%` | `10.86` | `-2.82%` | `670` | Preferred aggressive baseline |
| Top5 abs-weighted | `5x` | `$2,008,281` | `200.83%` | `11.41` | `-2.20%` | `845` | More diversified, slightly lower return |
| Top8 abs-weighted | `5x` | `$1,896,126` | `189.61%` | `12.13` | `-2.00%` | `971` | Diversified, smoother |

Preferred aggressive baseline:

1. `Top3 abs-weighted at 5x`.
2. Use `Top2 abs-weighted at 5x` only when the top two funding signals are
   unusually dominant and both legs are executable with acceptable liquidity.
3. Fall back to `Top5 abs-weighted at 5x` when signal strength is more evenly
   distributed or when a top symbol has questionable IBKR option liquidity.

Suggested dynamic TOPN rule:

- Start from `Top3`.
- If `top2_abs_funding / top5_abs_funding_sum` is very high, allow `Top2`.
- If the third to fifth signals are close in strength, use `Top5`.
- Exclude or cap symbols with weak IBKR option liquidity, large basis, or
  unreliable Binance depth.

The aggressive view does not mean liquidation risk is zero. It means the
strategy should not be penalized as if Binance last-trade high/low directly
sets the liquidation path during non-US trading hours. A production version
still needs a mark-price-based liquidation model using Binance's actual TradFi
mark-price rules.

## TOPN Scan Frequency

Backtest frequency:

- TOPN is recomputed once per Binance funding interval.
- For TradFi USDT perpetuals this means every 8 hours on the settlement grid:
  `00:00`, `08:00`, and `16:00 UTC`.

Live execution recommendation:

- Scan continuously or on a short polling interval for monitoring, but only
  make TOPN rebalance decisions around the next Binance funding settlement.
- Practical schedule: run the decision scan 5-10 minutes before each
  `nextFundingTime`, then place or adjust positions before the funding snapshot.
- Also run a post-settlement reconciliation scan after funding is credited or
  debited.

This keeps turnover tied to the actual funding payment cycle while still giving
the execution layer enough time to hedge the IBKR leg.

## Next Research Directions

The next research pass should move from funding-only PnL to execution-quality
PnL. Priority items:

1. Binance perp mark vs IBKR underlying basis

   - Measure `Binance TradFi perp mark price / index price` against the IBKR
     stock or ETF reference price.
   - Track basis at funding decision time, US market open, US market close, and
     high-volatility events.
   - Separate regular trading hours from overnight, weekend, and holiday
     sessions.
   - Output by symbol: median basis, 95th percentile basis, worst basis, and
     basis half-life.

2. Open convergence after US market open

   - Measure convergence between Binance perp mark and IBKR reference price
     after the US cash open.
   - Required checkpoints: `5m`, `15m`, and `30m` after open.
   - For gap days, compare pre-open Binance mark, opening IBKR price, and
     post-open convergence path.
   - Goal: quantify whether open gaps are neutralized quickly enough for the
     hedge assumption to hold.

3. IBKR synthetic option closing spread

   - Estimate the real cost to close the synthetic hedge:
     long synthetic = long call + short put, short synthetic = short call +
     long put.
   - Measure bid/ask spread for both option legs at entry, rebalance, and exit.
   - Report cost as bps of underlying notional by symbol, expiry, moneyness,
     time of day, and volatility regime.
   - Flag symbols where option liquidity makes the hedge unacceptable even when
     funding is attractive.

4. Funding coverage of basis and execution costs

   - For each candidate trade, compare expected funding income against:
     Binance taker/maker fees, Binance slippage, Binance/IBKR basis, IBKR
     synthetic spread, and hedge timing error.
   - Convert this into a net expected edge per 8h period.
   - Add a trade filter: only enter when expected funding exceeds estimated
     all-in execution and basis cost by a required safety margin.

Research deliverable:

- A symbol-level table ranking TradFi contracts by net executable edge, not raw
  funding rate.
- A revised TOPN allocator that ranks by expected net edge after basis and hedge
  costs.
- A live monitor field showing `raw_funding_edge`, `basis_cost_estimate`,
  `ibkr_spread_cost_estimate`, and `net_edge`.

## Caveats

- The sample is short and includes unusually large 2026 funding events.
- The main return table does not model Binance order book depth, slippage,
  margin interest, exchange limits, or execution latency.
- The liquidation stress section is approximate and should be replaced with a
  symbol-tier-aware Binance liquidation-price engine before production sizing.
- The current comparison keeps the existing backtest accounting convention:
  same-direction notional changes do not incur extra rebalance fees unless a
  position is opened, closed, or flipped.
- A production-grade version should use pre-settlement observable rates and
  explicitly model execution timing.
