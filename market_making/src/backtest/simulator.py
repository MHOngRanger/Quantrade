"""Market-making simulator."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..model.avellaneda_stoikov import make_quote


def rolling_sigma2(mid: pd.Series, window: int = 60) -> pd.Series:
    """Estimate rolling variance of simple returns."""
    returns = mid.pct_change()
    return returns.rolling(window).var().bfill().fillna(0.0)


def time_to_close(index: pd.Index) -> pd.Series:
    """Simple normalized remaining time within each trading day."""
    ts = pd.DatetimeIndex(index)
    day_groups = pd.Series(range(len(ts)), index=ts).groupby(ts.date)
    tau = pd.Series(1.0, index=ts)
    for _, positions in day_groups:
        n = len(positions)
        if n <= 1:
            tau.loc[positions.index] = 0.0
        else:
            tau.loc[positions.index] = np.linspace(1.0, 0.0, n)
    return tau


def run_simulation(
    mid: pd.Series,
    *,
    gamma: float = 0.1,
    kappa: float = 1.5,
    lot_size: float = 1.0,
    max_inventory: float = 10.0,
    fee_bps: float = 0.5,
    seed: int = 42,
) -> pd.DataFrame:
    """Run a simple Avellaneda-Stoikov market-making simulation."""
    rng = np.random.default_rng(seed)
    mid = mid.dropna().astype(float)
    sigma2 = rolling_sigma2(mid).reindex(mid.index).fillna(0.0)
    tau = time_to_close(mid.index).reindex(mid.index).fillna(1.0)

    inventory = 0.0
    cash = 0.0
    rows: list[dict] = []
    fee = fee_bps / 10_000

    for ts, price in mid.items():
        quote = make_quote(
            price,
            inventory,
            gamma=gamma,
            sigma2=float(sigma2.loc[ts]),
            tau=float(tau.loc[ts]),
            kappa=kappa,
        )
        half_spread = max((quote.ask - quote.bid) / 2, 0.01)
        base_prob = min(0.5, np.exp(-kappa * half_spread / max(price, 1e-9)))

        can_buy = inventory + lot_size <= max_inventory
        can_sell = inventory - lot_size >= -max_inventory
        bid_fill = bool(can_buy and rng.random() < base_prob)
        ask_fill = bool(can_sell and rng.random() < base_prob)

        if bid_fill:
            inventory += lot_size
            cash -= quote.bid * lot_size * (1 + fee)
        if ask_fill:
            inventory -= lot_size
            cash += quote.ask * lot_size * (1 - fee)

        rows.append(
            {
                "ts": ts,
                "mid": price,
                "reservation_price": quote.reservation_price,
                "bid": quote.bid,
                "ask": quote.ask,
                "spread": quote.spread,
                "bid_fill": int(bid_fill),
                "ask_fill": int(ask_fill),
                "inventory": inventory,
                "cash": cash,
                "mark_to_market": cash + inventory * price,
            }
        )

    return pd.DataFrame(rows).set_index("ts")

